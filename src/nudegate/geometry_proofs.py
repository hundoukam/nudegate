"""Bind intersection acceptance to the exact source and authored mesh geometry."""
import hashlib
import json
import math
import re
import statistics


def validate_geometry_proof(source, authored, proof):
    from .surface_intersections import geometry_fingerprint
    source_positions,source_triangles,source_topology = source.positions,source.triangles,source.topology_id
    authored_positions,authored_triangles,authored_topology = authored.positions,authored.triangles,authored.topology_id
    if (not isinstance(proof,dict) or proof.get('schema_version')!=1
            or proof.get('algorithm')!='bvh-plane-interval-coplanar-clip-v1'
            or proof.get('predicate_version')!='adaptive-exact-nearplane-v2'
            or proof.get('safe') is not True):
        raise ValueError('Expansion requires a passed actual surface intersection proof')
    if proof.get('tolerances')!={'linear':1e-9,'source_weld_distance':1e-7,
                               'triangle_area':1e-12,'parallel_sine':1e-10}:
        raise ValueError('Surface proof uses unreviewed geometric tolerances')
    if source_triangles != authored_triangles or source_topology != authored_topology:
        raise ValueError('Surface proof requires unchanged source topology')
    if (proof.get('topology_id')!=source_topology
            or proof.get('source_geometry_sha256')!=geometry_fingerprint(source_positions,source_triangles)
            or proof.get('candidate_geometry_sha256')!=geometry_fingerprint(authored_positions,authored_triangles)
            or proof.get('position_count')!=len(authored_positions)
            or proof.get('triangle_count')!=len(authored_triangles)):
        raise ValueError('Surface proof is not bound to these source and authored positions')
    for key in ('introduced_intersection_count','new_collapsed_faces','reference_normal_turns',
                'source_intersection_count','candidate_intersection_count','resolved_intersection_count'):
        if type(proof.get(key)) is not int or proof[key]<0:
            raise ValueError('Invalid surface proof count: '+key)
    if proof['introduced_intersection_count'] or proof['new_collapsed_faces']:
        raise ValueError('Expansion introduced triangle intersections or collapsed faces')
    pairs = {}
    for name in ('source','candidate','introduced','resolved'):
        entries = proof.get(name+'_intersection_pairs')
        if not isinstance(entries,list):
            raise ValueError('Surface proof requires explicit triangle pair records')
        found = set()
        for pair in entries:
            if (not isinstance(pair,list) or len(pair)!=2 or any(type(i) is not int for i in pair)
                    or not 0<=pair[0]<pair[1]<len(authored_triangles) or tuple(pair) in found):
                raise ValueError('Invalid surface intersection pair')
            found.add(tuple(pair))
        if len(found)!=proof[name+'_intersection_count']:
            raise ValueError('Surface pair records disagree with their count')
        pairs[name]=found
    if (pairs['introduced']!=pairs['candidate']-pairs['source']
            or pairs['resolved']!=pairs['source']-pairs['candidate']):
        raise ValueError('Surface proof pair comparison is inconsistent')
    digest = hashlib.sha256(json.dumps(sorted(pairs['source']),separators=(',',':')).encode()).hexdigest()
    if digest!=proof.get('source_intersection_pair_sha256'):
        raise ValueError('Source intersection pair fingerprint differs')
    return True


def validate_wall_calibration(record, source, baked, *, family_id, profile_sha256, frame):
    from .surface_intersections import geometry_fingerprint
    source_positions,source_triangles,source_topology = source.positions,source.triangles,source.topology_id
    baked_positions,baked_triangles = baked.positions,baked.triangles
    if (not isinstance(record,dict) or record.get('schema_version')!=1
            or type(record.get('source_lod')) is not int or record['source_lod']!=0
            or record.get('family_id')!=family_id or record.get('profile_sha256')!=profile_sha256
            or not isinstance(profile_sha256,str) or not re.fullmatch('[0-9a-f]{64}',profile_sha256)
            or record.get('frame')!=frame or record.get('source_topology_id')!=source_topology
            or record.get('source_geometry_sha256')!=geometry_fingerprint(source_positions,source_triangles)
            or record.get('baked_geometry_sha256')!=geometry_fingerprint(baked_positions,baked_triangles)
            or record.get('source_vertex_count')!=len(source_positions)
            or record.get('source_triangle_count')!=len(source_triangles)):
        raise ValueError('Wall calibration is not bound to this family and its authored LOD0 base')
    expected = hashlib.sha256(json.dumps({k:v for k,v in record.items() if k!='calibration_sha256'},
        sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    if record.get('calibration_sha256')!=expected:
        raise ValueError('Wall calibration record changed after authoring')
    landmarks = record.get('wall_landmark_vertices')
    if (not isinstance(landmarks,list) or not landmarks
            or any(type(index) is not int or not 0<=index<len(source_positions) for index in landmarks)
            or len(set(landmarks))!=len(landmarks)):
        raise ValueError('Invalid wall calibration landmarks')
    wall = record.get('wall_z')
    if (isinstance(wall,bool) or not isinstance(wall,(int,float)) or not math.isfinite(wall)
            or wall!=statistics.median(baked_positions[index][2] for index in landmarks)):
        raise ValueError('Wall calibration differs from its measured LOD0 landmarks')
    return True
