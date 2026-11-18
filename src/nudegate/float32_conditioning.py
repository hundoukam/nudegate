"""Explicit bounded Float32 representation conditioning, never a predicate tolerance.

Only reviewed, fingerprinted callers should use this. The helper proves bounded
coordinate/copy parity; it does not establish surface safety. A fresh complete
geometry audit and serialized readback are still required.
"""
from __future__ import annotations
import math
from pathlib import Path
import numpy as np

MAXIMUM_REPRESENTATION_ERROR_METRES = 2e-7


def require_unconditioned_stage(report, stage):
    """Keep the representation-error budget relative to one original stage."""
    stage=Path(stage)
    if ('post_neck_numeric_conditioning' in report
            or any((stage/name).exists() for name in
                ('numeric-conditioning-config.json','numeric-conditioning-parity.json'))):
        raise ValueError('Already-conditioned source stage: start from the original unconditioned stage')


def condition_float32_vector(positions, *, expected_position, expected_rows,
                             conditioned_position, maximum_error_m):
    """Apply one reviewed vector to all coincident copies under one norm cap.

    Changed components must be exactly Float32-representable. Unlike the
    one-step helper, small coordinates may move multiple ULPs; the Euclidean
    error is always measured from the original captured Float64 coordinate.
    """
    p=np.asarray(positions);before=np.asarray(expected_position,dtype=np.float64)
    after=np.asarray(conditioned_position,dtype=np.float64)
    if (p.dtype!=np.dtype(np.float64)or p.ndim!=2 or p.shape[1:]!=(3,)or not len(p)
            or not np.isfinite(p).all()or before.shape!=(3,)or after.shape!=(3,)
            or not np.isfinite(before).all()or not np.isfinite(after).all()):
        raise ValueError('Conditioning requires finite captured Float64 N by 3 positions and vectors')
    if (not isinstance(expected_rows,(list,tuple))or not expected_rows
            or any(type(row)is not int for row in expected_rows)):
        raise ValueError('Invalid reviewed coincident copy IDs')
    if (isinstance(maximum_error_m,bool)or not isinstance(maximum_error_m,(int,float))
            or not math.isfinite(maximum_error_m)or not 0<maximum_error_m<=MAXIMUM_REPRESENTATION_ERROR_METRES):
        raise ValueError('Representation error bound must be positive and at most 2e-7 metres')
    rows=np.flatnonzero(np.all(p==before,axis=1))
    if rows.tolist()!=list(expected_rows):raise ValueError('Original position or complete coincident copy IDs changed')
    axes=np.flatnonzero(after!=before)
    if not len(axes):raise ValueError('Reviewed vector must change at least one component')
    if not np.array_equal(after[axes],after[axes].astype(np.float32).astype(np.float64)):
        raise ValueError('Changed components must be exactly Float32-representable')
    error=float(np.linalg.norm(after-before))
    if error>maximum_error_m:raise ValueError('Vector conditioning exceeds its Euclidean representation error bound')
    result=p.copy()
    for axis in axes:result[rows,axis]=after[axis]
    unaffected=np.ones(len(p),bool);unaffected[rows]=False
    assert result[unaffected].tobytes()==p[unaffected].tobytes()
    for axis in range(3):
        if axis not in axes:assert result[:,axis].tobytes()==p[:,axis].tobytes()
    def ordered(value):
        bits=int(np.asarray(np.float32(value)).view(np.uint32))
        return (~bits&0xffffffff)if bits&0x80000000 else bits|0x80000000
    return result,{'export_vertex_ids':rows.tolist(),'before_float64_position':before.tolist(),
        'after_float64_position':after.tolist(),'changed_axes':axes.tolist(),
        'before_float32_position':before.astype(np.float32).astype(float).tolist(),
        'after_float32_position':after.astype(np.float32).astype(float).tolist(),
        'ulp_steps_per_axis':[ordered(after[i])-ordered(before[i])for i in range(3)],
        'displacement_from_original_float64_m':error,'maximum_allowed_error_m':maximum_error_m,
        'coincident_copy_count':len(rows),'all_other_position_components_bit_exact':True}


def condition_float32_step(positions, *, expected_position, expected_rows, axis,
                           ulp_direction, expected_before_float32,
                           expected_after_float32, maximum_error_m):
    """Return a copy with exactly one component stepped to its next Float32.

    Every exactly coincident copy is moved together. All other Float64 values,
    including signed zeros, remain bit-identical. Expected coordinates and row
    identities must match before any mutation is performed.
    """
    p = np.asarray(positions)
    expected = np.asarray(expected_position, dtype=np.float64)
    if (p.dtype != np.dtype(np.float64) or p.ndim != 2 or p.shape[1:] != (3,)
            or not len(p) or not np.isfinite(p).all()
            or expected.shape != (3,) or not np.isfinite(expected).all()):
        raise ValueError('Conditioning requires finite captured Float64 N by 3 positions')
    if (type(axis) is not int or not 0 <= axis < 3
            or type(ulp_direction) is not int or ulp_direction not in (-1, 1)
            or not isinstance(expected_rows, (list, tuple))
            or not expected_rows or any(type(row) is not int for row in expected_rows)):
        raise ValueError('Invalid reviewed coordinate, direction or copy IDs')
    if (isinstance(maximum_error_m, bool) or not isinstance(maximum_error_m, (int, float))
            or not math.isfinite(maximum_error_m) or not 0 < maximum_error_m <= MAXIMUM_REPRESENTATION_ERROR_METRES):
        raise ValueError('Representation error bound must be positive and at most 2e-7 metres')
    rows = np.flatnonzero(np.all(p == expected, axis=1))
    if rows.tolist() != list(expected_rows):
        raise ValueError('Original position or complete coincident copy IDs changed')
    before32 = np.float32(expected[axis])
    after32 = np.nextafter(before32, np.float32(-np.inf if ulp_direction < 0 else np.inf), dtype=np.float32)
    if (not np.isfinite(before32) or not np.isfinite(after32)
            or float(before32) != expected_before_float32 or float(after32) != expected_after_float32):
        raise ValueError('Reviewed exact Float32 neighbours changed')
    error = abs(float(after32)-float(expected[axis]))
    if error > maximum_error_m:
        raise ValueError('One-ULP conditioning exceeds its representation error bound')
    result = p.copy()
    result[rows, axis] = float(after32)
    unaffected = np.ones(len(p), dtype=bool)
    unaffected[rows] = False
    assert result[unaffected].tobytes() == p[unaffected].tobytes()
    for other in range(3):
        if other != axis:
            assert result[:, other].tobytes() == p[:, other].tobytes()
    return result, {'export_vertex_ids': rows.tolist(), 'axis': axis, 'ulp_direction': ulp_direction,
        'before_float64_position': expected.tolist(), 'before_float32_component': float(before32),
        'after_float32_component': float(after32), 'float32_ulp_shift_m': float(abs(after32-before32)),
        'displacement_from_original_float64_m': float(error), 'maximum_allowed_error_m': maximum_error_m,
        'coincident_copy_count': len(rows), 'all_other_position_components_bit_exact': True}
