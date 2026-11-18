// Selection/order audit around the exact nicoco007/lslib ClothUtils.cs,
// commit 9ce136678ade9a14d57b05897cfa47e6d6622803 (MIT; see NOTICE.txt).
// Its selection/ordering reproduces all five native TJiU buffers byte-for-byte.
// Its general nearest-three heuristics require explicit --allow-nearest opt-in.
using System.IO.Compression;
using System.Collections;
using System.Reflection;
using LSLib.Granny.Model;
using OpenTK.Mathematics;

internal static class ClothMapping {
    internal const double Radius=0.0000001f;
    internal sealed class Marked {
        internal List<Vertex> Vertices;
        internal List<int> Indices;
        internal List<int>[] Neighbors;
        internal HashSet<int> Selection;
        internal byte[] Masks;
    }
    static byte Byte(float value)=>checked((byte)(value*255));
    static (long,long,long) Cell(Vector3 p)=>(checked((long)Math.Floor(p.X/Radius)),checked((long)Math.Floor(p.Y/Radius)),checked((long)Math.Floor(p.Z/Radius)));
    internal static Marked Select(Mesh mesh) {
        var vertices=mesh.PrimaryVertexData.Vertices;var indices=mesh.PrimaryTopology.Indices;
        var cells=new Dictionary<(long,long,long),List<int>>();
        for(int i=0;i<vertices.Count;i++) {var cell=Cell(vertices[i].Position);if(!cells.TryGetValue(cell,out var list))cells[cell]=list=new List<int>();list.Add(i);}
        var overlaps=new List<int>[vertices.Count];var neighbors=Enumerable.Range(0,vertices.Count).Select(_=>new HashSet<int>()).ToArray();
        var weights=vertices.Select(v=>Byte(v.Color0.X)).ToArray();var originalWeights=(byte[])weights.Clone();
        for(int i=0;i<vertices.Count;i++) {
            var p=vertices[i].Position;var (x,y,z)=Cell(p);var near=new List<int>();
            for(int a=-1;a<=1;a++)for(int b=-1;b<=1;b++)for(int c=-1;c<=1;c++)if(cells.TryGetValue((x+a,y+b,z+c),out var candidates))foreach(var j in candidates) {
                var q=vertices[j].Position;double dx=(double)p.X-q.X,dy=(double)p.Y-q.Y,dz=(double)p.Z-q.Z;
                if(dx*dx+dy*dy+dz*dz<=Radius*Radius)near.Add(j);
            }
            overlaps[i]=near;weights[i]=originalWeights[near.Min()];
        }
        for(int i=0;i<indices.Count;i+=3)for(int c=0;c<3;c++) {
            neighbors[indices[i+c]].Add(indices[i+(c+1)%3]);neighbors[indices[i+c]].Add(indices[i+(c+2)%3]);
        }
        var selected=Enumerable.Range(0,vertices.Count).Where(i=>weights[i]>0).ToHashSet();
        foreach(var relation in new IEnumerable<int>[][]{overlaps,neighbors.Select(n=>(IEnumerable<int>)n).ToArray(),overlaps,neighbors.Select(n=>(IEnumerable<int>)n).ToArray(),overlaps})
            foreach(var j in selected.ToArray().SelectMany(i=>relation[i]))selected.Add(j);
        return new Marked{Vertices=vertices,Indices=indices,Neighbors=neighbors.Select(n=>n.Order().ToList()).ToArray(),Selection=selected,Masks=vertices.Select(v=>Byte(v.Color0.Z)).ToArray()};
    }
    internal static (int[] Vertices,int[] Indices) ExtractProxy(Mesh body) {
        var marked=Select(body);var triangles=new List<int>();
        for(int i=0;i<marked.Indices.Count;i+=3)if(Enumerable.Range(0,3).Any(c=>marked.Selection.Contains(marked.Indices[i+c])))triangles.AddRange(marked.Indices.Skip(i).Take(3));
        if(triangles.Count==0)throw new InvalidDataException("Body has no painted cloth patch");
        var used=triangles.Distinct().Order().ToArray();var map=used.Select((v,i)=>(v,i)).ToDictionary(p=>p.v,p=>p.i);
        return (used,triangles.Select(i=>map[i]).ToArray());
    }
    static object Property(object obj,string name) {
        for(var type=obj.GetType();type!=null;type=type.BaseType) {
            var p=type.GetProperty(name,BindingFlags.NonPublic|BindingFlags.Public|BindingFlags.Instance|BindingFlags.DeclaredOnly);
            if(p!=null)return p.GetValue(obj);
        }
        throw new InvalidDataException("Pinned primary vertex metadata missing: "+name);
    }
    static void AuditPrimaryOrder(Root root,int[] targets,List<Vector3> points,List<byte> masks) {
        // Pin this audit to the copied source's own private selection/packing.
        // Equal counts alone cannot prove equal selected raw-vertex order.
        var primary=typeof(LSLib.Granny.ClothUtils);var flags=BindingFlags.NonPublic|BindingFlags.Static;
        var build=primary.GetNestedType("ClothMesh",BindingFlags.NonPublic).GetMethod("Build",flags);
        var body=build.Invoke(null,new object[]{root.Meshes[0]});var proxy=build.Invoke(null,new object[]{root.Meshes[1]});
        var target=((IEnumerable)primary.GetMethod("GetTargetClothVertices",flags).Invoke(null,new[]{body})).Cast<object>().ToArray();
        var physics=((IEnumerable)primary.GetMethod("GetPhysicsClothVertices",flags).Invoke(null,new[]{proxy})).Cast<object>().ToArray();
        if(!target.Select(v=>(int)Property(v,"Index")).SequenceEqual(targets)||physics.Length!=points.Count)throw new InvalidDataException("Primary selection/packing differs from independent audit");
        for(int i=0;i<physics.Length;i++)if((Vector3)Property(physics[i],"Position")!=points[i]||(byte)Property(physics[i],"Mask")!=masks[i]||(short)Property(physics[i],"PhysicsIndex")!=i)throw new InvalidDataException("Primary cooked physics order/mask differs from independent audit");
    }
    internal static object Generate(Root root,bool allowNearest=false) {
        var body=Select(root.Meshes[0]);var proxy=Select(root.Meshes[1]);
        var physics=new Dictionary<Vector3,int>();var masks=new List<byte>();var physicalPositions=new List<Vector3>();
        for(int i=0;i<proxy.Indices.Count;i+=3) {
            if(!Enumerable.Range(0,3).All(c=>proxy.Selection.Contains(proxy.Indices[i+c])))continue;
            for(int c=0;c<3;c++) {var index=proxy.Indices[i+c];var p=proxy.Vertices[index].Position;
                if(!physics.ContainsKey(p)) {physics.Add(p,physics.Count);masks.Add(proxy.Masks[index]);physicalPositions.Add(p);}
            }
        }
        if(physics.Count==0||physics.Count>short.MaxValue)throw new InvalidDataException("Unsupported cooked proxy vertex count");
        var chosen=body.Selection.Order().ToArray();var packed=Enumerable.Repeat(-1,chosen.Length).ToArray();int next=0,current=0;
        while(next<chosen.Length&&chosen[next]<chosen.Length) {packed[chosen[next]]=chosen[next];next++;}
        while(next<chosen.Length) {while(packed[current]>=0)current++;packed[current++]=chosen[next++];}
        AuditPrimaryOrder(root,packed,physicalPositions,masks);
        var triplets=LSLib.Granny.ClothUtils.Generate(root.Meshes[1],root.Meshes[0]);
        if(triplets.Length!=packed.Length)throw new InvalidDataException("Primary mapping selection diverged from audited order");
        var distances=new List<double>();var slotCounts=new int[4];int noncoincident=0;double maxNeighbor=0;
        using var raw=new MemoryStream();using(var writer=new BinaryWriter(raw,System.Text.Encoding.UTF8,true))for(int i=0;i<packed.Length;i++) {
            var vertex=body.Vertices[packed[i]];var t=triplets[i];var entries=new[]{t.A,t.B,t.C};
            if(t.A<0)throw new InvalidDataException("Marked render vertex has no compatible physics neighbor");
            double firstDistance=0;int slots=0;
            for(int j=0;j<3;j++) {
                int physical=entries[j];writer.Write(entries[j]);if(physical<0)continue;slots++;
                if(physical>=physicalPositions.Count||(body.Masks[packed[i]]!=0&&(body.Masks[packed[i]]&masks[physical])==0))throw new InvalidDataException("Primary mapping index/mask invalid");
                double distance=(vertex.Position-physicalPositions[physical]).Length;maxNeighbor=Math.Max(maxNeighbor,distance);if(j==0)firstDistance=distance;
            }
            if(firstDistance!=0)noncoincident++;distances.Add(firstDistance);slotCounts[slots]++;
            if(!allowNearest&&(firstDistance!=0||t.B!=-1||t.C!=-1))throw new InvalidDataException("Strict coincident mapping requires an exact physics counterpart: "+packed[i]);
        }
        byte[] bytes=raw.ToArray();using var compressed=new MemoryStream();
        using(var zlib=new ZLibStream(compressed,CompressionLevel.SmallestSize,true))zlib.Write(bytes);
        distances.Sort();double Quantile(double q)=>distances.Count==0?0:distances[(int)Math.Round((distances.Count-1)*q)];
        return new {schema_version=1,algorithm=allowNearest?"primary-nearest-cloth-map-v1":"coincident-cloth-map-v1",source_algorithm="nicoco007/lslib@9ce136678ade9a14d57b05897cfa47e6d6622803",
            target_marked_vertices=packed.Length,physics_selected_positions=physics.Count,nb_closest_vertices=packed.Length*3,
            closest_vertices=Convert.ToBase64String(compressed.ToArray()),closest_vertices_u16_le_base64=Convert.ToBase64String(bytes),raw_buffer_sha256=NativeState.Hash(bytes),sha256_raw=NativeState.Hash(bytes),
            noncoincident_vertices=noncoincident,nearest_distance_metres=new{minimum=Quantile(0),median=Quantile(.5),p95=Quantile(.95),maximum=Quantile(1)},maximum_neighbor_distance_metres=maxNeighbor,
            neighbor_slot_counts=slotCounts,physics_mesh=root.Meshes[1].Name,proxy_mesh=root.Meshes[1].Name,target_mesh=root.Meshes[0].Name,
            target_raw_indices=packed,overlap_radius=Radius,primary_selection_and_cooked_order_exact=true,allow_nearest=allowNearest};
    }
}
