// Narrow LSLib 1.20.4 authoring exporter for a complete matched render/proxy pair.
// Generic COLLADA import quantizes cloth colors and transforms. Capture original
// vertex records through the library's resolved NodeSerializer metadata, then
// change only explicitly named Position/QTangent fields. All other records,
// native rig data, skinning, UVs and cloth flags must survive the read-back proof.
// Runtime cloth behavior and triangle intersection checks are separate work.
using System.Collections;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Buffers.Binary;
using System.Globalization;
using System.Xml.Linq;
using OpenTK.Mathematics;
using LSLib.Granny.GR2;
using LSLib.Granny.Model;

static class PhysicsExport {
    static CaptureVertices captured;
    static string Hash(byte[] bytes)=>Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
    static (Root,uint,string[]) Load(string path) {
        using var stream=File.OpenRead(path);
        using var reader=new GR2Reader(stream);
        var root=new Root(); reader.Read(root); var tag=reader.Tag;
        var rawTypes=(IDictionary)typeof(GR2Reader).GetField("Types",BindingFlags.NonPublic|BindingFlags.Instance).GetValue(reader);
        var schemas=new List<string>();
        foreach(var def in rawTypes.Values) {
            var members=(IEnumerable)def.GetType().GetField("Members").GetValue(def);
            var signatures=new List<string>();
            foreach(var member in members) {
                var t=member.GetType();
                signatures.Add($"{t.GetField("Name").GetValue(member)}:{t.GetField("Type").GetValue(member)}:{t.GetField("ArraySize").GetValue(member)}");
            }
            schemas.Add(string.Join("|",signatures));
        }
        root.PostLoad(tag);
        return (root,tag,schemas.Distinct().Order().ToArray());
    }
    static (Root,uint,string[]) LoadPreserved(string path) {
        using var stream1=File.OpenRead(path);
        using var reader1=new GR2Reader(stream1);
        var ignored=new Root();reader1.Read(ignored);
        var definitions=(IDictionary)typeof(GR2Reader).GetField("Types",BindingFlags.NonPublic|BindingFlags.Instance).GetValue(reader1);
        captured=new CaptureVertices();
        foreach(StructDefinition definition in definitions.Values) {
            if(definition.Type==typeof(VertexData)) {
                var vertices=definition.Members.Single(m=>m.Name=="Vertices");
                captured.Original=vertices.Serializer;vertices.Serializer=captured;
            }
        }
        using var stream2=File.OpenRead(path);using var reader2=new GR2Reader(stream2);
        var cache=(IDictionary)typeof(GR2Reader).GetField("Types",BindingFlags.NonPublic|BindingFlags.Instance).GetValue(reader2);
        foreach(DictionaryEntry pair in definitions)cache.Add(pair.Key,pair.Value);
        var root=new Root();reader2.Read(root);
        captured.Original16Bit=root.TriTopologies.Where(t=>t.Indices16!=null).ToHashSet(ReferenceEqualityComparer.Instance);
        root.PostLoad(reader2.Tag);
        return (root,reader2.Tag,Array.Empty<string>());
    }
    static object Scalar(object value,Dictionary<object,int> visited,bool omitGeometry=false) {
        if(value is null)return null;
        var type=value.GetType();
        if(value is float f)return new[]{"f32",BitConverter.SingleToInt32Bits(f).ToString("x8")};
        if(value is double d)return new[]{"f64",BitConverter.DoubleToInt64Bits(d).ToString("x16")};
        if(type.IsPrimitive||value is string||type.IsEnum)return type.FullName+":"+value;
        if(!type.IsValueType) {
            if(visited.TryGetValue(value,out var id))return new[]{"ref",id.ToString()};
            visited[value]=visited.Count;
        }
        if(value is IEnumerable list) {
            var items=new List<object>();foreach(var item in list)items.Add(Scalar(item,visited,omitGeometry));
            return items;
        }
        var fields=new SortedDictionary<string,object>();
        foreach(var field in type.GetFields(BindingFlags.Public|BindingFlags.Instance).OrderBy(f=>f.Name)) {
            if(omitGeometry&&value is Vertex&&new[]{"Position","Normal","Tangent","Binormal"}.Contains(field.Name))continue;
            var serialization=field.GetCustomAttributes().FirstOrDefault(a=>a.GetType().Name=="SerializationAttribute");
            if(serialization!=null) {
                var kind=serialization.GetType().GetField("Kind")?.GetValue(serialization)?.ToString()
                    ??serialization.GetType().GetProperty("Kind")?.GetValue(serialization)?.ToString();
                if(kind=="None")continue;
            }
            fields[field.Name]=Scalar(field.GetValue(value),visited,omitGeometry);
        }
        return new object[]{type.FullName,fields};
    }
    static byte[] Canonical(Root root,bool omitGeometry=false)=>JsonSerializer.SerializeToUtf8Bytes(Scalar(root,new Dictionary<object,int>(ReferenceEqualityComparer.Instance),omitGeometry));
    static void ValidatePair(Root root) {
        if(root.Meshes?.Count!=2||root.Models?.Count!=1||root.Models[0].MeshBindings.Count!=2
            ||!root.Models[0].MeshBindings.Select(b=>b.Mesh).SequenceEqual(root.Meshes))
            throw new InvalidDataException("Requires one complete matched render/proxy model");
        for(int i=0;i<2;i++) {
            var mesh=root.Meshes[i];var properties=mesh.ExtendedData?.UserMeshProperties;
            if(properties==null||!properties.MeshFlags.IsCloth()
                ||properties.ClothFlags.HasClothPhysics()!=(i==1)||mesh.ExportOrder!=i
                ||!mesh.VertexFormat.HasBoneWeights||mesh.VertexFormat.ColorMaps<1)
                throw new InvalidDataException("Source lacks ordered skinned cloth render/proxy data");
        }
    }
    static double[][] Positions(XElement geometry,XNamespace ns) {
        var mesh=geometry.Element(ns+"mesh");
        var reference=mesh.Element(ns+"vertices").Elements(ns+"input").Single(i=>(string)i.Attribute("semantic")=="POSITION").Attribute("source").Value.TrimStart('#');
        var source=mesh.Elements(ns+"source").Single(s=>(string)s.Attribute("id")==reference);
        var accessor=source.Element(ns+"technique_common").Element(ns+"accessor");
        if((string)accessor.Attribute("stride")!="3"||((int?)accessor.Attribute("offset")??0)!=0)throw new InvalidDataException("Expected unoffset XYZ positions");
        var values=source.Element(ns+"float_array").Value.Split((char[])null,StringSplitOptions.RemoveEmptyEntries).Select(s=>double.Parse(s,CultureInfo.InvariantCulture)).ToArray();
        if(values.Length%3!=0||(int?)source.Element(ns+"float_array").Attribute("count")!=values.Length||(int?)accessor.Attribute("count")!=values.Length/3)throw new InvalidDataException("Position array/accessor count mismatch");
        if(values.Any(v=>!double.IsFinite(v)))throw new InvalidDataException("Nonfinite positions");
        return Enumerable.Range(0,values.Length/3).Select(i=>values.Skip(i*3).Take(3).ToArray()).ToArray();
    }
    static int[] Triangles(XElement geometry,XNamespace ns) => geometry.Element(ns+"mesh").Elements(ns+"triangles").SelectMany(p=> {
        var inputs=p.Elements(ns+"input");var stride=inputs.Max(i=>(int?)i.Attribute("offset")??0)+1;
        var offset=(int?)inputs.Single(i=>(string)i.Attribute("semantic")=="VERTEX").Attribute("offset")??0;
        var values=p.Element(ns+"p").Value.Split((char[])null,StringSplitOptions.RemoveEmptyEntries).Select(int.Parse).ToArray();
        return Enumerable.Range(0,values.Length/stride).Select(i=>values[i*stride+offset]);
    }).ToArray();
    static List<object> Apply(Root root,CaptureVertices capture,string referencePath,string authorPath,string jacobianPath) {
        var reference=XDocument.Load(referencePath);var authored=XDocument.Load(authorPath);
        XNamespace ns=reference.Root.Name.Namespace;
        var refs=reference.Root.Element(ns+"library_geometries").Elements(ns+"geometry").ToArray();
        var authors=authored.Root.Element(ns+"library_geometries").Elements(ns+"geometry").ToArray();
        if(refs.Length!=root.Meshes.Count||authors.Length!=refs.Length)throw new InvalidDataException("Expected the entire matched body/proxy set");
        using var json=JsonDocument.Parse(File.ReadAllText(jacobianPath));var fields=json.RootElement.GetProperty("geometries");
        if(fields.EnumerateObject().Count()!=root.Meshes.Count)throw new InvalidDataException("Expected one Jacobian field for every matched geometry");
        var reports=new List<object>();
        foreach(var mesh in root.Meshes) {
            var rd=refs.Single(g=>(string)g.Attribute("name")==mesh.Name);
            var ad=authors.Single(g=>(string)g.Attribute("id")== (string)rd.Attribute("id"));
            var old=Positions(rd,ns);var target=Positions(ad,ns);
            var jacobians=fields.GetProperty((string)rd.Attribute("id")).GetProperty("jacobians");
            var data=mesh.PrimaryVertexData;data.Deduplicate();var map=data.Deduplicator.Vertices.DeduplicationMap;
            var originalPositions=data.Deduplicator.Vertices.Uniques.Select(v=>v.Position).ToArray();
            if(old.Length!=originalPositions.Length||target.Length!=old.Length||jacobians.GetArrayLength()!=old.Length)throw new InvalidDataException("Position/Jacobian counts differ");
            for(int i=0;i<old.Length;i++)if((originalPositions[i]-new Vector3((float)old[i][0],(float)old[i][1],(float)old[i][2])).Length>1e-6)throw new InvalidDataException("Reference DAE differs from original GR2");
            if(!Triangles(rd,ns).SequenceEqual(mesh.PrimaryTopology.Indices.Select(i=>map[i]))||!Triangles(rd,ns).SequenceEqual(Triangles(ad,ns)))throw new InvalidDataException("Indexed body/proxy correspondence changed");
            var bytes=capture.Blocks[data.Vertices];var layout=capture.Layouts[data.Vertices];var stride=bytes.Length/data.Vertices.Count;
            var position=layout.Single(f=>f.Name=="Position");var qtangent=layout.Single(f=>f.Name=="QTangent");
            if(position.Size!=12||qtangent.Size!=8)throw new InvalidDataException("Unsupported source position/basis format");
            int moved=0,bent=0;double minDet=double.PositiveInfinity;
            for(int i=0;i<data.Vertices.Count;i++) {
                var v=data.Vertices[i];var index=map[i];var j=jacobians[index];
                if(j.GetArrayLength()!=3||j.EnumerateArray().Any(r=>r.GetArrayLength()!=3))throw new InvalidDataException("Jacobian must be3x3");
                double[][] matrix=j.EnumerateArray().Select(r=>r.EnumerateArray().Select(x=>x.GetDouble()).ToArray()).ToArray();
                if(matrix.SelectMany(r=>r).Any(x=>!double.IsFinite(x)))throw new InvalidDataException("Nonfinite Jacobian");
                var a=new Vector3((float)matrix[0][0],(float)matrix[1][0],(float)matrix[2][0]);
                var b=new Vector3((float)matrix[0][1],(float)matrix[1][1],(float)matrix[2][1]);
                var c=new Vector3((float)matrix[0][2],(float)matrix[1][2],(float)matrix[2][2]);
                var determinant=Vector3.Dot(a,Vector3.Cross(b,c));minDet=Math.Min(minDet,determinant);
                if(determinant<1e-5||!float.IsFinite(determinant))throw new InvalidDataException("Locally inverted or singular deformation");
                bool samePosition=old[index].SequenceEqual(target[index]);
                if(!samePosition) {
                    v.Position=new Vector3((float)target[index][0],(float)target[index][1],(float)target[index][2]);
                    var span=bytes.AsSpan(i*stride+position.Offset,12);
                    BinaryPrimitives.WriteSingleLittleEndian(span,v.Position.X);BinaryPrimitives.WriteSingleLittleEndian(span.Slice(4),v.Position.Y);BinaryPrimitives.WriteSingleLittleEndian(span.Slice(8),v.Position.Z);
                    for(int k=0;k<12;k++)capture.Allowed[data.Vertices].Add(i*stride+position.Offset+k);moved++;
                }
                bool identity=Enumerable.Range(0,3).All(r=>Enumerable.Range(0,3).All(col=>Math.Abs(matrix[r][col]-(r==col?1:0))<1e-8));
                if(!identity) {
                    var originalNormal=v.Normal;var originalTangent=v.Tangent;var originalBinormal=v.Binormal;
                    var normal=(Vector3.Cross(b,c)*originalNormal.X+Vector3.Cross(c,a)*originalNormal.Y+Vector3.Cross(a,b)*originalNormal.Z)/determinant;
                    normal.Normalize();var tangent=a*originalTangent.X+b*originalTangent.Y+c*originalTangent.Z;
                    tangent=(tangent-normal*Vector3.Dot(normal,tangent)).Normalized();
                    var handedness=Vector3.Dot(Vector3.Cross(originalNormal,originalTangent),originalBinormal)<0?-1:1;
                    var binormal=Vector3.Cross(normal,tangent).Normalized()*handedness;
                    v.Normal=normal;v.Tangent=tangent;v.Binormal=binormal;
                    var pack=v.Clone();pack.Tangent=binormal;pack.Binormal=tangent;
                    var temporaryWriter=new GR2Writer();var section=new WritableSection(SectionType.Main,temporaryWriter);
                    VertexSerializationHelpers.Serialize(section,pack);var encoded=section.MainStream.ToArray();
                    if(encoded.Length!=stride)throw new InvalidDataException("Vertex encoding stride differs");
                    encoded.AsSpan(qtangent.Offset,8).CopyTo(bytes.AsSpan(i*stride+qtangent.Offset,8));
                    section.MainWriter.Dispose();section.DataWriter.Dispose();temporaryWriter.Dispose();
                    for(int k=0;k<8;k++)capture.Allowed[data.Vertices].Add(i*stride+qtangent.Offset+k);bent++;
                }
            }
            reports.Add(new{mesh=mesh.Name,indexed_positions=old.Length,raw_vertices=data.Vertices.Count,moved_vertices=moved,transported_basis_vertices=bent,minimum_sampled_jacobian_determinant=minDet});
        }
        return reports;
    }
    static object Describe(Root root) => new {
        meshes=root.Meshes.Select(m=>new {
            name=m.Name,raw_vertices=m.PrimaryVertexData.Vertices.Count,
            colors=m.PrimaryVertexData.Vertices.Select(v=>new[]{v.Color0.X,v.Color0.Y,v.Color0.Z,v.Color0.W}).Distinct(new FloatsComparer()).ToArray(),
            first_vertex_format=Scalar(m.PrimaryVertexData.Vertices[0].Format,new Dictionary<object,int>(ReferenceEqualityComparer.Instance)),
        }).ToArray(),
        canonical_sha256=Hash(Canonical(root))
    };
    public static int Main(string[] args) {
        try {return Run(args);}catch(Exception error) {Console.Error.WriteLine(error.Message);return 1;}
    }
    static int Run(string[] args) {
        bool debug=args.Length>0&&args.Last()=="--debug-state";
        if(debug)args=args[..^1];
        if(args.Length!=2&&args.Length!=5) {
            Console.Error.WriteLine("Usage: PhysicsExport source.GR2 output.GR2 [reference.dae authored.dae jacobians.json] [--debug-state]");return 2;
        }
        var finalOutput=Path.GetFullPath(args[1]);
        if(String.Equals(finalOutput,Path.GetFullPath(args[0]),StringComparison.OrdinalIgnoreCase))throw new ArgumentException("Output must not replace its source");
        for(var entry=new FileInfo(finalOutput).Directory;entry!=null;entry=entry.Parent)
            if(entry.Exists&&(entry.Attributes&FileAttributes.ReparsePoint)!=0)throw new ArgumentException("Output parent may not be a link");
        if(File.Exists(finalOutput)&&(File.GetAttributes(finalOutput)&FileAttributes.ReparsePoint)!=0)throw new ArgumentException("Output may not be a link");
        Directory.CreateDirectory(Path.GetDirectoryName(finalOutput));
        string tempOutput=finalOutput+".partial-"+Guid.NewGuid().ToString("N");
        var pinPath=Path.Combine(AppContext.BaseDirectory,"toolchain-pins.json");
        var pins=JsonSerializer.Deserialize<Dictionary<string,string>>(File.ReadAllText(pinPath));
        foreach(var pin in pins)if(Hash(File.ReadAllBytes(Path.Combine(AppContext.BaseDirectory,pin.Key)))!=pin.Value)throw new InvalidDataException("Authoring toolchain hash changed: "+pin.Key);
        var inputPaths=(args.Length==5?new[]{args[0],args[2],args[3],args[4]}:new[]{args[0]}).Select(Path.GetFullPath).Distinct(OperatingSystem.IsWindows()?StringComparer.OrdinalIgnoreCase:StringComparer.Ordinal).ToArray();
        var inputHashes=inputPaths.ToDictionary(p=>p,p=>Hash(File.ReadAllBytes(p)));
        try {
        var (_,_,schemas)=Load(args[0]);
        var (root,tag,_ignored)=LoadPreserved(args[0]);
        ValidatePair(root);
        var originalCapture=captured;
        var sourceRaw=root.Meshes.ToDictionary(m=>m.Name,m=>Hash(captured.Blocks[m.PrimaryVertexData.Vertices]));
        var before=Canonical(root);var beforeDescription=Describe(root);
        var protectedBefore=Canonical(root,true);
        var authoring=args.Length>=5?Apply(root,captured,args[2],args[3],args[4]):new List<object>();
        // Preserve the reviewed original 16-bit topology representation too.
        foreach(var topology in root.TriTopologies) {
            if(originalCapture.Original16Bit.Contains(topology)) {
                if(topology.Indices.Any(i=>i<0||i>ushort.MaxValue))throw new InvalidDataException("Original16-bit index range changed");
                topology.Indices16=topology.Indices.Select(i=>(ushort)i).ToList();topology.Indices=null;
            }
        }
        var writer=new GR2Writer{Format=Magic.Format.LittleEndian64,AlternateMagic=true,VersionTag=tag};
        var lookup=typeof(GR2Writer).GetMethod("LookupStructDefinition",BindingFlags.Instance|BindingFlags.NonPublic);
        var vd=(StructDefinition)lookup.Invoke(writer,new object[]{typeof(VertexData),root.VertexDatas[0]});
        vd.Members.Single(m=>m.Name=="Vertices").Serializer=captured;
        File.WriteAllBytes(tempOutput,writer.Write(root,(uint)root.Meshes.Count));writer.Dispose();
        var (after,afterTag,afterSchemas)=Load(tempOutput);
        var afterBytes=Canonical(after);
        var (afterPreserved,_,_ignoreAgain)=LoadPreserved(tempOutput);
        var rawExact=afterPreserved.Meshes.All(m=>sourceRaw[m.Name]==Hash(captured.Blocks[m.PrimaryVertexData.Vertices]));
        var nonGeometryExact=protectedBefore.SequenceEqual(Canonical(after,true));
        bool unrelatedBytesExact=true;
        foreach(var mesh in root.Meshes) {
            var target=afterPreserved.Meshes.Single(m=>m.Name==mesh.Name);
            var original=originalCapture.OriginalBlocks[mesh.PrimaryVertexData.Vertices];var actual=captured.Blocks[target.PrimaryVertexData.Vertices];
            var allowed=originalCapture.Allowed[mesh.PrimaryVertexData.Vertices];
            if(original.Length!=actual.Length||Enumerable.Range(0,original.Length).Any(i=>!allowed.Contains(i)&&original[i]!=actual[i]))unrelatedBytesExact=false;
        }
        double positionError=0,basisAngle=0;
        foreach(var mesh in root.Meshes) {
            var target=after.Meshes.Single(m=>m.Name==mesh.Name);
            for(int i=0;i<mesh.PrimaryVertexData.Vertices.Count;i++) {
                var expected=mesh.PrimaryVertexData.Vertices[i];var actual=target.PrimaryVertexData.Vertices[i];
                positionError=Math.Max(positionError,(expected.Position-actual.Position).Length);
                foreach(var pair in new[]{(expected.Normal,actual.Normal),(expected.Tangent,actual.Tangent),(expected.Binormal,actual.Binormal)}) {
                    double dot=(double)pair.Item1.X*pair.Item2.X+(double)pair.Item1.Y*pair.Item2.Y+(double)pair.Item1.Z*pair.Item2.Z;
                    double length=Math.Sqrt(((double)pair.Item1.X*pair.Item1.X+(double)pair.Item1.Y*pair.Item1.Y+(double)pair.Item1.Z*pair.Item1.Z)*((double)pair.Item2.X*pair.Item2.X+(double)pair.Item2.Y*pair.Item2.Y+(double)pair.Item2.Z*pair.Item2.Z));
                    if(length>1e-20)basisAngle=Math.Max(basisAngle,Math.Acos(Math.Clamp(dot/length,-1,1))*180/Math.PI);
                }
            }
        }
        bool valid=tag==afterTag&&nonGeometryExact&&unrelatedBytesExact&&schemas.SequenceEqual(afterSchemas)&&positionError==0&&basisAngle<.05;
        if(authoring.Count==0)valid&=rawExact&&before.SequenceEqual(afterBytes);
        if(!valid)throw new InvalidDataException("Protected data or authored basis verification failed");
        if(inputHashes.Any(p=>Hash(File.ReadAllBytes(p.Key))!=p.Value))throw new InvalidDataException("An input changed during export");
        var report=new {schema_version=1,validation_status="passed",input=Path.GetFullPath(args[0]),source_sha256=inputHashes[Path.GetFullPath(args[0])],output=finalOutput,
            output_sha256=Hash(File.ReadAllBytes(tempOutput)),tag,tag_unchanged=tag==afterTag,
            reference_dae_sha256=args.Length>=5?Hash(File.ReadAllBytes(args[2])):null,
            authored_dae_sha256=args.Length>=5?Hash(File.ReadAllBytes(args[3])):null,
            jacobians_sha256=args.Length>=5?Hash(File.ReadAllBytes(args[4])):null,
            toolchain_pins=pins,helper_assembly_sha256=Hash(File.ReadAllBytes(Assembly.GetExecutingAssembly().Location)),
            protected_state_sha256=Hash(protectedBefore),readback_protected_state_sha256=Hash(Canonical(after,true)),
            max_position_serialization_error=positionError,max_basis_angular_error_degrees=basisAngle,
            in_game_physics="not tested",new_gravity_or_squeeze="not implemented",
            non_geometry_state_exact=nonGeometryExact,unrelated_vertex_record_bytes_exact=unrelatedBytesExact,authoring,
            raw_vertex_records_exact=rawExact,source_raw_vertex_hashes=sourceRaw,
            full_known_object_state_exact=before.SequenceEqual(afterBytes),before=beforeDescription,after=Describe(after),
            source_schema_missing=schemas.Except(afterSchemas).ToArray(),new_schemas=afterSchemas.Except(schemas).ToArray()};
        File.Move(tempOutput,finalOutput,true);
        File.WriteAllText(finalOutput+".report.json",JsonSerializer.Serialize(report,new JsonSerializerOptions{WriteIndented=true}));
        if(debug) {File.WriteAllBytes(finalOutput+".before.json",before);File.WriteAllBytes(finalOutput+".after.json",afterBytes);}
        Console.WriteLine(JsonSerializer.Serialize(new{report.full_known_object_state_exact,report.raw_vertex_records_exact,report.non_geometry_state_exact,report.unrelated_vertex_record_bytes_exact,report.tag_unchanged,
            missing_schema_count=report.source_schema_missing.Length,new_schema_count=report.new_schemas.Length}));
        return 0;
        } finally {if(File.Exists(tempOutput))File.Delete(tempOutput);}
    }
}
class CaptureVertices:NodeSerializer {
    public record Layout(string Name,int Offset,int Size);
    public NodeSerializer Original;
    public HashSet<object> Original16Bit=new(ReferenceEqualityComparer.Instance);
    public Dictionary<object,byte[]> Blocks=new(ReferenceEqualityComparer.Instance);
    public Dictionary<object,byte[]> OriginalBlocks=new(ReferenceEqualityComparer.Instance);
    public Dictionary<object,HashSet<int>> Allowed=new(ReferenceEqualityComparer.Instance);
    public Dictionary<object,List<Layout>> Layouts=new(ReferenceEqualityComparer.Instance);
    public object Read(GR2Reader reader,StructDefinition definition,MemberDefinition member,uint arraySize,object parent) {
        var binary=(BinaryReader)typeof(GR2Reader).GetField("Reader",BindingFlags.NonPublic|BindingFlags.Instance).GetValue(reader);
        var start=binary.BaseStream.Position;
        var length=checked((int)(definition.Size(reader)*arraySize));
        var bytes=binary.ReadBytes(length);
        if(bytes.Length!=length)throw new InvalidDataException("Truncated vertex block");
        binary.BaseStream.Position=start;
        var result=Original.Read(reader,definition,member,arraySize,parent);
        if(binary.BaseStream.Position!=start+length)throw new InvalidDataException("Vertex record size mismatch");
        Blocks.Add(result,bytes);
        OriginalBlocks.Add(result,(byte[])bytes.Clone());Allowed.Add(result,new HashSet<int>());
        int offset=0;var layout=new List<Layout>();
        foreach(var field in definition.Members) {
            int size=checked((int)field.TotalSize(reader));layout.Add(new Layout(field.Name,offset,size));offset+=size;
        }
        if(offset*arraySize!=length)throw new InvalidDataException("Resolved vertex layout differs from captured data");
        Layouts.Add(result,layout);
        return result;
    }
    public void Write(GR2Writer writer,WritableSection section,MemberDefinition member,object obj) {
        var vertices=(List<Vertex>)obj;
        if(vertices.Count>0)section.StoreObjectOffset(vertices[0]);
        section.Writer.Write(Blocks[obj]);
    }
}
class FloatsComparer:IEqualityComparer<float[]> {
    public bool Equals(float[] a,float[] b)=>a.SequenceEqual(b);
    public int GetHashCode(float[] a)=>a.Aggregate(0,(h,v)=>HashCode.Combine(h,v));
}
