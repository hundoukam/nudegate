using LSLib.Granny.Model;

internal static class GeometryReadback {
    static byte[] PackPositions(Mesh m) {
        using var bytes=new MemoryStream();using var writer=new BinaryWriter(bytes);
        foreach(var v in m.PrimaryVertexData.Vertices){writer.Write(v.Position.X);writer.Write(v.Position.Y);writer.Write(v.Position.Z);}return bytes.ToArray();
    }
    static byte[] PackIndices(Mesh m) {
        using var bytes=new MemoryStream();using var writer=new BinaryWriter(bytes);
        foreach(var index in m.PrimaryTopology.Indices)writer.Write(index);return bytes.ToArray();
    }
    internal static object Generate(string path) {
        var hash=NativeState.FileHash(path);var root=NativeState.Load(path);
        var meshes=root.Meshes.Select(m=>{
            var positions=PackPositions(m);var indices=PackIndices(m);var props=m.ExtendedData.UserMeshProperties;
            return new {
                name=m.Name,raw_vertices=m.PrimaryVertexData.Vertices.Count,triangles=m.PrimaryTopology.Indices.Count/3,
                positions_f32_le_base64=Convert.ToBase64String(positions),positions_f32_le_sha256=NativeState.Hash(positions),
                triangle_indices_i32_le_base64=Convert.ToBase64String(indices),triangle_indices_i32_le_sha256=NativeState.Hash(indices),
                material_groups=m.PrimaryTopology.Groups.Select(g=>new{tri_first=g.TriFirst,tri_count=g.TriCount,material_index=g.MaterialIndex}).ToArray(),
                all_triangles_bound=m.PrimaryTopology.Groups.Count==1&&m.PrimaryTopology.Groups[0].TriFirst==0&&m.PrimaryTopology.Groups[0].TriCount==m.PrimaryTopology.Indices.Count/3,
                export_order=m.ExportOrder,mesh_flags=props.MeshFlags.ToString(),cloth_flags=props.ClothFlags.ToString(),bone_palette=m.BoneBindings.Select(b=>b.BoneName).ToArray()
            };
        }).ToArray();
        if(NativeState.FileHash(path)!=hash)throw new InvalidDataException("Geometry input changed during readback");
        return new {schema_version=1,source_gr2=Path.GetFullPath(path),source_sha256=hash,coordinate_system="BG3 Y-up native GR2 Float3",binary_encoding="little-endian IEEE754 float32 xyz rows and signed int32 triangle index rows; raw serialized vertex/index order",meshes};
    }
}
