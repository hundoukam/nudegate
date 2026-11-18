using System.Text.Json;
using LSLib.Granny.GR2;
using LSLib.Granny.Model;
using OpenTK.Mathematics;

internal static class DonorMeshExport {
    static float[] Row(JsonElement data,int size) {
        if(data.GetArrayLength()!=size)throw new InvalidDataException("Incorrect vector width");
        // Payload numbers round-trip authored Float64 NPZ values. Convert through
        // that exact double before Float3 narrowing, matching np.float32(author).
        // Direct decimal GetSingle can differ at halfway cases by one ULP.
        var row=data.EnumerateArray().Select(v=>(float)v.GetDouble()).ToArray();if(row.Any(v=>!float.IsFinite(v)))throw new InvalidDataException("Nonfinite component");return row;
    }
    static int[] IntRow(JsonElement data,int size,int maximum) {
        if(data.GetArrayLength()!=size)throw new InvalidDataException("Incorrect integer vector width");
        var row=data.EnumerateArray().Select(v=>v.GetInt32()).ToArray();if(row.Any(v=>v<0||v>maximum))throw new InvalidDataException("Component outside integer range");return row;
    }
    static Vector3 Vector(JsonElement value) {var a=Row(value,3);return new Vector3(a[0],a[1],a[2]);}
    static byte Encoded(float value)=>checked((byte)MathF.Round(value*255));
    static float Color(int value)=>value==255?1:(value+.25f)/255;
    static void Basis(Vertex v) {
        var n=v.Normal;var t=v.Tangent;var b=v.Binormal;
        if(Math.Abs(n.Length-1)>.01||Math.Abs(t.Length-1)>.01||Math.Abs(b.Length-1)>.01
            ||Math.Abs(Vector3.Dot(n,t))>.02||Math.Abs(Vector3.Dot(n,b))>.02||Math.Abs(Vector3.Dot(t,b))>.02)
            throw new InvalidDataException("Basis must be normalized and orthogonal");
    }
    static void CheckTemplate(Mesh mesh) {
        if(mesh.MorphTargets?.Count>0||mesh.PrimaryVertexData.VertexAnnotationSets?.Count>0||mesh.PrimaryTopology.TriAnnotationSets?.Count>0)
            throw new InvalidDataException("Template has unsupported indexed annotations/morphs");
        if(mesh.PrimaryTopology.Groups.Count!=1||mesh.BoneBindings.Any(b=>b.TriangleIndices?.Count>0))throw new InvalidDataException("Template requires unsupported material/bone triangle maps");
        var t=mesh.PrimaryTopology;
        if(new[]{t.VertexToVertexMap,t.VertexToTriangleMap,t.SideToNeighborMap,t.PolygonIndexStarts,t.PolygonIndices,t.BonesForTriangle,t.TriangleToBoneIndices}.Any(v=>v?.Count>0))
            throw new InvalidDataException("Template has unsupported indexed auxiliary maps");
        var f=mesh.VertexFormat;
        if(f.PositionType!=PositionType.Float3||f.NormalType!=NormalType.QTangent||f.ColorMapType!=ColorMapType.Byte4||f.ColorMaps!=1||f.TextureCoordinates!=1||f.TextureCoordinateType!=TextureCoordinateType.Half2||f.NumBoneInfluences!=4)
            throw new InvalidDataException("Unsupported native vertex layout");
    }
    static void Topology(Mesh mesh,List<int> indices) {
        if(indices.Count==0||indices.Count%3!=0)throw new InvalidDataException("Expected nonempty triangles");
        var count=mesh.PrimaryVertexData.Vertices.Count;
        if(indices.Any(i=>i<0||i>=count))throw new InvalidDataException("Triangle index outside vertex array");
        for(int i=0;i<indices.Count;i+=3)if(indices[i]==indices[i+1]||indices[i+1]==indices[i+2]||indices[i+2]==indices[i])throw new InvalidDataException("Repeated triangle vertex");
        mesh.PrimaryTopology.Indices=indices;mesh.PrimaryTopology.Indices16=null;
        mesh.PrimaryTopology.Groups[0].TriFirst=0;mesh.PrimaryTopology.Groups[0].TriCount=indices.Count/3;
    }
    static void Fill(Mesh mesh,JsonElement payload,Skeleton skeleton,bool allowHead) {
        var names=payload.GetProperty("bone_palette").EnumerateArray().Select(x=>x.GetString()).ToArray();
        if(names.Length==0||names.Distinct().Count()!=names.Length)throw new InvalidDataException("Bone palette is empty/duplicated");
        var native=mesh.BoneBindings.Select((b,i)=>(b.BoneName,i)).ToDictionary(x=>x.BoneName,x=>x.i);
        var skeletonNames=skeleton.Bones.Select(b=>b.Name).ToHashSet();
        if(names.Any(n=>!skeletonNames.Contains(n)))throw new InvalidDataException("Payload includes joints absent from the native skeleton");
        var fields=new[]{"positions","normals","tangents","binormals","uvs","colors_rgba8","bone_indices","bone_weights"}.ToDictionary(k=>k,k=>payload.GetProperty(k));
        int count=fields["positions"].GetArrayLength();if(count<3||count>65535||fields.Any(f=>f.Value.GetArrayLength()!=count))throw new InvalidDataException("Vertex components have mismatched/unsupported counts");
        var used=new HashSet<string>();
        for(int i=0;i<count;i++) {var b=IntRow(fields["bone_indices"][i],4,names.Length-1);var w=IntRow(fields["bone_weights"][i],4,255);if(w.Sum()!=255)throw new InvalidDataException("Each integer skin-weight row must sum to255");for(int j=0;j<4;j++)if(w[j]>0)used.Add(names[b[j]]);}
        foreach(var name in used.Where(n=>!native.ContainsKey(n))) {
            if(name!="Head_M"||!allowHead)throw new InvalidDataException("Positively used joint is absent from original render palette: "+name);
            native.Add(name,mesh.BoneBindings.Count);mesh.BoneBindings.Add(new BoneBinding{BoneName=name,OBBMin=new float[3],OBBMax=new float[3]});
        }
        var remap=names.Select(n=>native.TryGetValue(n,out int i)?i:0).ToArray();if(remap.Any(i=>i>255))throw new InvalidDataException("Native bone palette exceeds byte range");
        var vertices=new List<Vertex>(count);
        for(int i=0;i<count;i++) {
            var v=mesh.VertexFormat.CreateInstance();v.Position=Vector(fields["positions"][i]);v.Normal=Vector(fields["normals"][i]);v.Tangent=Vector(fields["tangents"][i]);v.Binormal=Vector(fields["binormals"][i]);Basis(v);
            var uv=Row(fields["uvs"][i],2);v.TextureCoordinates0=new Vector2(uv[0],uv[1]);
            var color=IntRow(fields["colors_rgba8"][i],4,255);v.Color0=new Vector4(Color(color[0]),Color(color[1]),Color(color[2]),Color(color[3]));
            var bones=IntRow(fields["bone_indices"][i],4,names.Length-1);var weights=IntRow(fields["bone_weights"][i],4,255);
            if(weights.Sum()!=255)throw new InvalidDataException("Each integer skin-weight row must sum to255");
            for(int j=0;j<4;j++) {v.BoneIndices[j]=checked((byte)remap[bones[j]]);v.BoneWeights[j]=checked((byte)weights[j]);}
            vertices.Add(v);
        }
        mesh.PrimaryVertexData.Vertices=vertices;mesh.PrimaryVertexData.Deduplicator=null;
        var tris=payload.GetProperty("triangles").EnumerateArray().SelectMany(t=>IntRow(t,3,count-1)).ToList();Topology(mesh,tris);
    }
    static void Proxy(Mesh body,Mesh proxy) {
        var (used,indices)=ClothMapping.ExtractProxy(body);
        if(used.Length>65535)throw new InvalidDataException("Extracted proxy exceeds16-bit vertex range");
        var names=proxy.BoneBindings.Select((b,i)=>(b.BoneName,i)).ToDictionary(v=>v.BoneName,v=>v.i);
        var vertices=new List<Vertex>(used.Length);
        foreach(var i in used) {
            var original=body.PrimaryVertexData.Vertices[i];var v=proxy.VertexFormat.CreateInstance();
            v.Position=original.Position;v.Normal=original.Normal;v.Tangent=original.Tangent;v.Binormal=original.Binormal;v.TextureCoordinates0=original.TextureCoordinates0;v.Color0=original.Color0;
            for(int j=0;j<4;j++) {var name=body.BoneBindings[original.BoneIndices[j]].BoneName;if(!names.TryGetValue(name,out int index))throw new InvalidDataException("Proxy palette lacks body joint"+name);v.BoneIndices[j]=(byte)index;v.BoneWeights[j]=original.BoneWeights[j];}
            vertices.Add(v);
        }
        proxy.PrimaryVertexData.Vertices=vertices;proxy.PrimaryVertexData.Deduplicator=null;Topology(proxy,indices.ToList());
    }
    static double Angle(Vector3 a,Vector3 b) {
        double dot=(double)a.X*b.X+(double)a.Y*b.Y+(double)a.Z*b.Z;
        double aa=(double)a.X*a.X+(double)a.Y*a.Y+(double)a.Z*a.Z,bb=(double)b.X*b.X+(double)b.Y*b.Y+(double)b.Z*b.Z;
        return Math.Acos(Math.Clamp(dot/Math.Sqrt(aa*bb),-1,1))*180/Math.PI;
    }
    static object Verify(Mesh expected,Mesh actual,bool swapped=true) {
        var a=expected.PrimaryVertexData.Vertices;var b=actual.PrimaryVertexData.Vertices;
        if(a.Count!=b.Count||!expected.PrimaryTopology.Indices16.Select(i=>(int)i).SequenceEqual(actual.PrimaryTopology.Indices))throw new InvalidDataException("Export changed raw vertex count or triangle order");
        if(actual.PrimaryTopology.Groups.Count!=1||actual.PrimaryTopology.Groups[0].TriFirst!=0||actual.PrimaryTopology.Groups[0].TriCount!=actual.PrimaryTopology.Indices.Count/3||actual.PrimaryTopology.Groups[0].MaterialIndex!=expected.PrimaryTopology.Groups[0].MaterialIndex)throw new InvalidDataException("Readback material group does not bind every output triangle");
        double position=0,basis=0,uv=0;
        for(int i=0;i<a.Count;i++) {
            if(!a[i].BoneIndices.Equals(b[i].BoneIndices)||!a[i].BoneWeights.Equals(b[i].BoneWeights))throw new InvalidDataException("Export changed remapped skin arrays");
            for(int k=0;k<4;k++)if(Encoded(a[i].Color0[k])!=Encoded(b[i].Color0[k]))throw new InvalidDataException("Export changed RGBA byte");
            position=Math.Max(position,(a[i].Position-b[i].Position).Length);uv=Math.Max(uv,(a[i].TextureCoordinates0-b[i].TextureCoordinates0).Length);
            // Expected vertices were swapped immediately before the official QTangent writer.
            basis=Math.Max(basis,Math.Max(Angle(a[i].Normal,b[i].Normal),Math.Max(Angle(swapped?a[i].Binormal:a[i].Tangent,b[i].Tangent),Angle(swapped?a[i].Tangent:a[i].Binormal,b[i].Binormal))));
        }
        if(position!=0||basis>.05||uv>.002)throw new InvalidDataException("Position/basis/UV read-back drift exceeds budget");
        var group=actual.PrimaryTopology.Groups[0];
        return new {mesh=actual.Name,raw_vertices=b.Count,triangles=actual.PrimaryTopology.Indices.Count/3,material_group=new{tri_first=group.TriFirst,tri_count=group.TriCount,material_index=group.MaterialIndex},all_triangles_bound=true,position_error=position,maximum_basis_angle_degrees=basis,maximum_uv_quantization_error=uv,rgba_bytes_exact=true,remapped_skin_bytes_exact=true};
    }
    static (int WeightedPoints,int Outside,double MaximumExcess) BoundsCheck(Skeleton skeleton,Mesh mesh) {
        int count=0,outside=0;double maximum=0;
        foreach(var vertex in mesh.PrimaryVertexData.Vertices)for(int i=0;i<4;i++)if(vertex.BoneWeights[i]>0) {
            var binding=mesh.BoneBindings[vertex.BoneIndices[i]];var bone=skeleton.GetBoneByName(binding.BoneName);
            // Same row-major constructor as official ColladaHelpers.FloatsToMatrix.
            var a=bone.InverseWorldTransform;var inverse=new Matrix4(a[0],a[1],a[2],a[3],a[4],a[5],a[6],a[7],a[8],a[9],a[10],a[11],a[12],a[13],a[14],a[15]);
            var p=Vector3.TransformPosition(vertex.Position,inverse);count++;
            double excess=0;for(int j=0;j<3;j++)excess=Math.Max(excess,Math.Max(binding.OBBMin[j]-p[j],p[j]-binding.OBBMax[j]));
            if(excess>0)outside++;maximum=Math.Max(maximum,excess);
        }
        return (count,outside,maximum);
    }
    static void SafeOutput(string path,string source) {
        if(Path.GetFullPath(path).Equals(Path.GetFullPath(source),StringComparison.OrdinalIgnoreCase))throw new ArgumentException("Output must not replace input");
        for(var p=new FileInfo(path).Directory;p!=null;p=p.Parent)if(p.Exists&&(p.Attributes&FileAttributes.ReparsePoint)!=0)throw new ArgumentException("Output parent must not be a link");
        if(File.Exists(path)&&(File.GetAttributes(path)&FileAttributes.ReparsePoint)!=0)throw new ArgumentException("Output must not be a link");
    }
    public static int Main(string[] args) {try {return Run(args);}catch(Exception error) {Console.Error.WriteLine(error.GetBaseException().Message);return 1;}}
    static int Run(string[] args) {
        var pins=NativeState.VerifyTools();
        var flags=args.Where(a=>a.StartsWith("--",StringComparison.Ordinal)).ToHashSet();
        if(flags.Except(new[]{"--allow-nearest","--preserve-template-proxy","--allow-head-binding","--rebuild-mesh-bounds"}).Any())throw new ArgumentException("Unknown option");
        args=args.Where(a=>!a.StartsWith("--",StringComparison.Ordinal)).ToArray();bool allowNearest=flags.Contains("--allow-nearest"),preserveProxy=flags.Contains("--preserve-template-proxy"),allowHead=flags.Contains("--allow-head-binding"),rebuildBounds=flags.Contains("--rebuild-mesh-bounds");
        if(args.Length==3&&args[0]=="geometry") {
            SafeOutput(args[2],args[1]);var result=GeometryReadback.Generate(args[1]);Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(args[2])));File.WriteAllText(args[2],JsonSerializer.Serialize(result,new JsonSerializerOptions{WriteIndented=true}));Console.WriteLine("Actual serialized geometry read back");return 0;
        }
        if(args.Length==3&&args[0]=="selftest") {
            SafeOutput(args[2],args[1]);var result=MappingChecks.Run(NativeState.Load(args[1]));Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(args[2])));File.WriteAllText(args[2],JsonSerializer.Serialize(result,new JsonSerializerOptions{WriteIndented=true}));Console.WriteLine("Controlled cloth mapping checks passed");return 0;
        }
        if(args.Length==3&&args[0]=="map") {
            SafeOutput(args[2],args[1]);var root=NativeState.Load(args[1]);var mapping=ClothMapping.Generate(root,allowNearest);
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(args[2])));File.WriteAllText(args[2],JsonSerializer.Serialize(new{source_gr2=Path.GetFullPath(args[1]),source_sha256=NativeState.FileHash(args[1]),mapping},new JsonSerializerOptions{WriteIndented=true}));Console.WriteLine("Cloth mapping generated");return 0;
        }
        if(args.Length!=3) {Console.Error.WriteLine("Usage: DonorMeshExport template.GR2 payload.json output.GR2 OR map source.GR2 output.json");return 2;}
        var template=Path.GetFullPath(args[0]);var payloadPath=Path.GetFullPath(args[1]);var output=Path.GetFullPath(args[2]);SafeOutput(output,template);SafeOutput(output,payloadPath);
        foreach(var sidecar in new[]{output+".report.json",output+".mapping.json"}){SafeOutput(sidecar,template);SafeOutput(sidecar,payloadPath);}
        var templateHash=NativeState.FileHash(template);var payloadHash=NativeState.FileHash(payloadPath);
        using var json=JsonDocument.Parse(File.ReadAllText(payloadPath));var payload=json.RootElement;
        if(payload.GetProperty("schema_version").GetInt32()!=1)throw new InvalidDataException("Unsupported payload schema");
        preserveProxy|=payload.TryGetProperty("preserve_template_proxy",out var keep)&&keep.GetBoolean();
        NodeSerializer capture=null;System.Collections.IDictionary sourceBlocks=null;Root rootModel;
        if(preserveProxy) {var loaded=NativeState.LoadCaptured(template);rootModel=loaded.Root;capture=loaded.Capture;sourceBlocks=loaded.Blocks;}else rootModel=NativeState.Load(template);
        var rig=NativeState.Rig(rootModel);var metadata=rootModel.Meshes.Select(NativeState.MeshMetadata).ToArray();
        var originalCounts=rootModel.Meshes.Select(m=>m.BoneBindings.Count).ToArray();var prefixes=rootModel.Meshes.Select(m=>NativeState.Snapshot(m.BoneBindings)).ToArray();
        var bindingIdentity=rootModel.Meshes.Select(m=>NativeState.BindingIdentity(m.BoneBindings)).ToArray();
        var proxyVertices=rootModel.Meshes[1].PrimaryVertexData.Vertices;var proxyRaw=preserveProxy?(byte[])sourceBlocks[proxyVertices]:null;
        foreach(var mesh in rootModel.Meshes)CheckTemplate(mesh);
        var meshes=payload.GetProperty("meshes").EnumerateArray().ToArray();bool automatic=!preserveProxy&&payload.TryGetProperty("proxy_from_body",out var auto)&&auto.GetBoolean();
        if(meshes.Length!=((automatic||preserveProxy)?1:2)||meshes.Select(m=>m.GetProperty("name").GetString()).Distinct().Count()!=meshes.Length)throw new InvalidDataException("Expected exact named body/proxy payload");
        Fill(rootModel.Meshes[0],meshes.Single(m=>m.GetProperty("name").GetString()==rootModel.Meshes[0].Name),rootModel.Models[0].Skeleton,allowHead);
        if(automatic)Proxy(rootModel.Meshes[0],rootModel.Meshes[1]);else if(!preserveProxy)Fill(rootModel.Meshes[1],meshes.Single(m=>m.GetProperty("name").GetString()==rootModel.Meshes[1].Name),rootModel.Models[0].Skeleton,false);
        var oldBounds=rootModel.Meshes.Select(m=>BoundsCheck(rootModel.Models[0].Skeleton,m)).ToArray();
        for(int i=0;i<2;i++) {
            var mesh=rootModel.Meshes[i];
            if(rebuildBounds)VertexHelpers.UpdateOBBs(rootModel.Models[0].Skeleton,mesh);
            else if(mesh.BoneBindings.Count>originalCounts[i]) {
                var original=mesh.BoneBindings;mesh.BoneBindings=original.Select(b=>new BoneBinding{BoneName=b.BoneName,OBBMin=new float[3],OBBMax=new float[3]}).ToList();
                VertexHelpers.UpdateOBBs(rootModel.Models[0].Skeleton,mesh);
                for(int j=originalCounts[i];j<original.Count;j++) {original[j].OBBMin=mesh.BoneBindings[j].OBBMin;original[j].OBBMax=mesh.BoneBindings[j].OBBMax;}
                mesh.BoneBindings=original;
            }
            if(!preserveProxy||i==0)foreach(var v in mesh.PrimaryVertexData.Vertices)(v.Tangent,v.Binormal)=(v.Binormal,v.Tangent);
            mesh.PrimaryTopology.Indices16=mesh.PrimaryTopology.Indices.Select(i=>checked((ushort)i)).ToList();mesh.PrimaryTopology.Indices=null;
        }
        Directory.CreateDirectory(Path.GetDirectoryName(output));var temporary=output+".partial-"+Guid.NewGuid().ToString("N");
        try {
            NativeState.Save(rootModel,temporary,capture,preserveProxy?proxyVertices:null);var readback=NativeState.Load(temporary);
            if(NativeState.Rig(readback)!=rig)throw new InvalidDataException("Skeleton or model bindings changed");
            if(!metadata.SequenceEqual(readback.Meshes.Select(NativeState.MeshMetadata)))throw new InvalidDataException("Protected mesh names/materials/cloth flags/format changed");
            bool prefixesExact=true;
            for(int i=0;i<2;i++) {
                var bindings=readback.Meshes[i].BoneBindings.Take(originalCounts[i]).ToList();
                if(NativeState.BindingIdentity(bindings)!=bindingIdentity[i])throw new InvalidDataException("Original bone-binding names/order/auxiliary records changed");
                bool exact=NativeState.Snapshot(bindings)==prefixes[i];prefixesExact&=exact;if(!rebuildBounds&&!exact)throw new InvalidDataException("Original bone-binding prefix changed");
                if(NativeState.Snapshot(readback.Meshes[i].BoneBindings)!=NativeState.Snapshot(rootModel.Meshes[i].BoneBindings))throw new InvalidDataException("Written bone bounds differ from authored values");
            }
            var boundsChecks=readback.Meshes.Select((m,i)=>{var check=BoundsCheck(readback.Models[0].Skeleton,m);if(rebuildBounds&&check.Outside!=0)throw new InvalidDataException("Rebuilt bone bounds miss weighted readback positions");return new{mesh=m.Name,weighted_points=check.WeightedPoints,outside_original_bounds=oldBounds[i].Outside,original_maximum_excess=oldBounds[i].MaximumExcess,outside_readback_bounds=check.Outside,readback_maximum_excess=check.MaximumExcess};}).ToArray();
            bool proxyRawExact=false;if(preserveProxy) {var loaded=NativeState.LoadCaptured(temporary);proxyRawExact=proxyRaw.SequenceEqual((byte[])loaded.Blocks[loaded.Root.Meshes[1].PrimaryVertexData.Vertices]);if(!proxyRawExact)throw new InvalidDataException("Preserved proxy raw records changed");}
            var checks=rootModel.Meshes.Zip(readback.Meshes).Select((pair,i)=>Verify(pair.First,pair.Second,!(preserveProxy&&i==1))).ToArray();
            var map=ClothMapping.Generate(readback,allowNearest);
            var bounds=readback.Meshes.Select(m=>new {mesh=m.Name,min=new[]{m.PrimaryVertexData.Vertices.Min(v=>v.Position.X),m.PrimaryVertexData.Vertices.Min(v=>v.Position.Y),m.PrimaryVertexData.Vertices.Min(v=>v.Position.Z)},max=new[]{m.PrimaryVertexData.Vertices.Max(v=>v.Position.X),m.PrimaryVertexData.Vertices.Max(v=>v.Position.Y),m.PrimaryVertexData.Vertices.Max(v=>v.Position.Z)}}).ToArray();
            if(NativeState.FileHash(template)!=templateHash||NativeState.FileHash(payloadPath)!=payloadHash)throw new InvalidDataException("Input changed during export");
            var report=new {schema_version=1,validation_status="passed",validation_scope="serialization, protected metadata, and source-algorithm mapping only; geometry and runtime acceptance are separate",template,template_sha256=templateHash,payload=payloadPath,payload_sha256=payloadHash,output,output_sha256=NativeState.FileHash(temporary),
                toolchain_pins=pins,helper_sha256=NativeState.FileHash(typeof(DonorMeshExport).Assembly.Location),rig_state_sha256=rig,readback_rig_state_sha256=NativeState.Rig(readback),
                intended_changes=new[]{preserveProxy?"render geometry":"render/proxy geometry","render UV/color/skin arrays",rebuildBounds?"per-binding OBBMin/OBBMax":"original bone bounds retained","explicit native palette extension only when requested and positively used","cloth mapping"},proxy_from_body=automatic,preserve_template_proxy=preserveProxy,proxy_raw_records_exact=proxyRawExact,proxy_raw_records_sha256=proxyRaw==null?null:NativeState.Hash(proxyRaw),
                original_bone_binding_prefixes_exact=prefixesExact,original_binding_names_order_and_aux_exact=true,bone_bounds_rebuilt=rebuildBounds,bone_bounds_algorithm="LSLib1.20.4 VertexHelpers.UpdateOBBs: positive-weight vertex transformed by native inverse bone world matrix",bone_bounds_checks=boundsChecks,palette_extensions=readback.Meshes.Select((m,i)=>new {mesh=m.Name,original_count=originalCounts[i],appended=m.BoneBindings.Skip(originalCounts[i]).Select(b=>b.BoneName).ToArray()}).ToArray(),
                bounds,meshes=checks,mapping=map,
                in_game_physics="not tested",global_surface_intersections="requires separate acceptance proof",new_gravity_or_squeeze="not implemented"};
            File.Move(temporary,output,true);File.WriteAllText(output+".report.json",JsonSerializer.Serialize(report,new JsonSerializerOptions{WriteIndented=true}));File.WriteAllText(output+".mapping.json",JsonSerializer.Serialize(new{schema_version=1,source_gr2=output,source_sha256=NativeState.FileHash(output),validation_status="passed",rig_exact=true,bounds,mapping=map},new JsonSerializerOptions{WriteIndented=true}));Console.WriteLine("Dense donor model and cloth mapping verified");return 0;
        } finally {if(File.Exists(temporary))File.Delete(temporary);}
    }
}
