using System.Collections;
using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;
using LSLib.Granny.GR2;
using LSLib.Granny.Model;

internal static class NativeState {
    internal static string Hash(byte[] bytes)=>Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
    internal static string FileHash(string path)=>Hash(File.ReadAllBytes(path));
    internal static Dictionary<string,string> VerifyTools() {
        var pins=JsonSerializer.Deserialize<Dictionary<string,string>>(File.ReadAllText(Path.Combine(AppContext.BaseDirectory,"toolchain-pins.json")));
        var mapping=JsonSerializer.Deserialize<Dictionary<string,string>>(File.ReadAllText(Path.Combine(AppContext.BaseDirectory,"mapping-dependency-pins.json")));
        foreach(var pin in mapping)pins.Add(pin.Key,pin.Value);
        foreach(var pin in pins)if(FileHash(Path.Combine(AppContext.BaseDirectory,pin.Key))!=pin.Value)throw new InvalidDataException("Authoring toolchain changed: "+pin.Key);
        return pins;
    }
    internal static Root Load(string path) {
        using var stream=File.OpenRead(path);using var reader=new GR2Reader(stream);
        var root=new Root();reader.Read(root);root.PostLoad(reader.Tag);ValidatePair(root);return root;
    }
    internal static (Root Root,NodeSerializer Capture,IDictionary Blocks) LoadCaptured(string path) {
        var type=Assembly.Load("PhysicsExport").GetType("PhysicsExport",true);
        var loaded=((Root,uint,string[]))type.GetMethod("LoadPreserved",BindingFlags.Static|BindingFlags.NonPublic).Invoke(null,new object[]{path});
        var capture=type.GetField("captured",BindingFlags.Static|BindingFlags.NonPublic).GetValue(null);
        var blocks=(IDictionary)capture.GetType().GetField("Blocks").GetValue(capture);
        ValidatePair(loaded.Item1);return (loaded.Item1,(NodeSerializer)capture,blocks);
    }
    internal static void ValidatePair(Root root) {
        if(root.Meshes?.Count!=2||root.Models?.Count!=1||root.Models[0].MeshBindings.Count!=2
            ||!root.Models[0].MeshBindings.Select(b=>b.Mesh).SequenceEqual(root.Meshes))throw new InvalidDataException("Requires one ordered matched render/proxy model");
        for(int i=0;i<2;i++) {
            var m=root.Meshes[i];var p=m.ExtendedData?.UserMeshProperties;
            if(p==null||!p.MeshFlags.IsCloth()||p.ClothFlags.HasClothPhysics()!=(i==1)||m.ExportOrder!=i)throw new InvalidDataException("Source lacks ordered cloth render/proxy flags");
        }
    }
    internal static void Save(Root root,string path,NodeSerializer capture=null,object preservedVertices=null) {
        var writer=new GR2Writer{Format=Magic.Format.LittleEndian64,AlternateMagic=true,VersionTag=root.GR2Tag};
        if(capture!=null) {
            var lookup=typeof(GR2Writer).GetMethod("LookupStructDefinition",BindingFlags.NonPublic|BindingFlags.Instance);
            var definition=(StructDefinition)lookup.Invoke(writer,new object[]{typeof(VertexData),root.VertexDatas[0]});
            definition.Members.Single(m=>m.Name=="Vertices").Serializer=new SelectiveVertices(capture,preservedVertices);
        }
        try {File.WriteAllBytes(path,writer.Write(root,(uint)root.Meshes.Count));}finally {writer.Dispose();}
    }
    sealed class SelectiveVertices(NodeSerializer capture,object preserved):NodeSerializer {
        public object Read(GR2Reader reader,StructDefinition definition,MemberDefinition member,uint size,object parent)=>throw new NotSupportedException();
        public void Write(GR2Writer writer,WritableSection section,MemberDefinition member,object obj) {
            if(ReferenceEquals(obj,preserved))capture.Write(writer,section,member,obj);else new VertexSerializer().Write(writer,section,member,obj);
        }
    }
    internal static object Scalar(object value,Dictionary<object,int> visited) {
        if(value is null)return null;var type=value.GetType();
        if(value is Mesh mesh)return new[]{"mesh-reference",mesh.Name};
        if(value is float f)return new[]{"f32",BitConverter.SingleToInt32Bits(f).ToString("x8")};
        if(value is double d)return new[]{"f64",BitConverter.DoubleToInt64Bits(d).ToString("x16")};
        if(type.IsPrimitive||value is string||type.IsEnum)return type.FullName+":"+value;
        if(!type.IsValueType) {if(visited.TryGetValue(value,out var id))return new[]{"ref",id.ToString()};visited[value]=visited.Count;}
        if(value is IEnumerable list) {var items=new List<object>();foreach(var item in list)items.Add(Scalar(item,visited));return items;}
        var fields=new SortedDictionary<string,object>();
        foreach(var field in type.GetFields(BindingFlags.Public|BindingFlags.Instance).OrderBy(f=>f.Name)) {
            var attr=field.GetCustomAttributes().FirstOrDefault(a=>a.GetType().Name=="SerializationAttribute");
            var kind=attr?.GetType().GetField("Kind")?.GetValue(attr)?.ToString()??attr?.GetType().GetProperty("Kind")?.GetValue(attr)?.ToString();
            if(kind=="None")continue;fields[field.Name]=Scalar(field.GetValue(value),visited);
        }
        return new object[]{type.FullName,fields};
    }
    internal static string Snapshot(object value)=>Hash(JsonSerializer.SerializeToUtf8Bytes(Scalar(value,new Dictionary<object,int>(ReferenceEqualityComparer.Instance))));
    internal static string Rig(Root r)=>Snapshot(new object[]{r.Skeletons,r.Models,r.ArtToolInfo,r.ExporterInfo,r.FromFileName,r.Materials,r.Textures,r.Animations,r.TrackGroups,r.ExtendedData});
    internal static string BindingIdentity(IEnumerable<BoneBinding> bindings)=>Snapshot(bindings.Select(b=>new object[]{b.BoneName,b.TriangleIndices}).ToArray());
    internal static string MeshMetadata(Mesh m)=>Snapshot(new object[]{m.Name,m.MaterialBindings,m.ExtendedData,m.ExportOrder,m.VertexFormat});
}
