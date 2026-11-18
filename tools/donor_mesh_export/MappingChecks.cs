using System.Text.Json;
using System.Reflection;
using LSLib.Granny.Model;
using OpenTK.Mathematics;

internal static class MappingChecks {
    static Mesh Mesh(VertexDescriptor format,string name,Vector3[] positions,byte[] masks=null) {
        var vertices=positions.Select((p,i)=>{var v=format.CreateInstance();v.Position=p;v.Color0=new Vector4(1,0,masks==null?0:(masks[i]+.25f)/255,1);return v;}).ToList();
        return new Mesh{Name=name,PrimaryVertexData=new VertexData{Vertices=vertices},PrimaryTopology=new TriTopology{Indices=new List<int>{0,1,2}}};
    }
    static void Expect(Root r,short[][] expected) {
        var actual=LSLib.Granny.ClothUtils.Generate(r.Meshes[1],r.Meshes[0]);
        if(actual.Length!=expected.Length)throw new InvalidDataException("Synthetic mapping count changed");
        for(int i=0;i<actual.Length;i++)if(!new[]{actual[i].A,actual[i].B,actual[i].C}.SequenceEqual(expected[i]))throw new InvalidDataException("Synthetic mapping differs at row "+i);
    }
    internal static object Run(Root template) {
        // Authored Float64 midpoints found by final native readback. Direct
        // decimal GetSingle selected the odd neighbor; Float64 then Float32
        // must choose these explicitly known even Float32 values.
        using var halfway=JsonDocument.Parse("[1.2794767022132874,0.17643339186906815]");
        var row=(float[])typeof(DonorMeshExport).GetMethod("Row",BindingFlags.NonPublic|BindingFlags.Static).Invoke(null,new object[]{halfway.RootElement,2});
        if(row[0]!=1.2794766426086426f||row[1]!=0.17643338441848755f)throw new InvalidDataException("Authored Float64 midpoint narrowing must round to the even Float32 neighbor");
        var f=template.Meshes[0].VertexFormat;
        var positions=new[]{new Vector3(0,0,0),new Vector3(.04f,0,0),new Vector3(0,.07f,0)};
        var target=new[]{new Vector3(.001f,0,0),new Vector3(.018f,.012f,0),new Vector3(.018f,.028f,0)};
        var r=new Root{Meshes=new List<Mesh>{Mesh(f,"target",positions),Mesh(f,"proxy",positions)}};
        Expect(r,new[]{new short[]{0,-1,-1},new short[]{1,-1,-1},new short[]{2,-1,-1}});ClothMapping.Generate(r);
        r.Meshes[0]=Mesh(f,"target",target);
        Expect(r,new[]{new short[]{0,-1,-1},new short[]{0,1,-1},new short[]{0,1,2}});ClothMapping.Generate(r,true);
        bool strictRejected=false;try{ClothMapping.Generate(r);}catch(InvalidDataException){strictRejected=true;}if(!strictRejected)throw new InvalidDataException("Strict mode admitted noncoincident targets");
        r.Meshes[0]=Mesh(f,"target",target,new byte[]{2,1,2});r.Meshes[1]=Mesh(f,"proxy",positions,new byte[]{1,2,2});
        Expect(r,new[]{new short[]{1,2,-1},new short[]{0,-1,-1},new short[]{1,2,-1}});ClothMapping.Generate(r,true);
        r.Meshes[0]=Mesh(f,"target",target,new byte[]{4,4,4});
        bool maskRejected=false;try{ClothMapping.Generate(r,true);}catch(InvalidDataException){maskRejected=true;}if(!maskRejected)throw new InvalidDataException("Mapping admitted targets without compatible physics masks");
        return new {authored_float64_to_float32_halfway_even=true,coincident_rows=true,one_two_three_neighbor_rows=true,mask_filter=true,strict_noncoincident_rejection=true,no_compatible_neighbor_rejection=true,scope="Controlled source-algorithm and authoring precision checks, not engine simulation"};
    }
}
