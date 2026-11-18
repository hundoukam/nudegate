"""Compact donor-rest-shape fields and sampled Euler transport.

This is offline geometry math. Spatial Jacobians describe the sampled numerical
map; they do not establish global injectivity, collision safety or game physics.
The same field can be sampled on a render body and its matched physics proxy.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from typing import Callable

import numpy as np
from scipy.spatial import cKDTree


VERSION = 'wendland-c2-normalized-euler-v1'


def _number(value, name):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.integer, np.floating)):
        raise ValueError(name + ' must be a finite real number')
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(name + ' must be a finite real number')
    return result


def _array(value, name, shape=None):
    try:
        result = np.asarray(value)
        if result.dtype.kind not in 'iuf':
            raise ValueError(name + ' must contain real numeric coordinates')
        result = np.asarray(result, dtype=np.float64)
    except (TypeError, OverflowError) as error:
        raise ValueError(name + ' must contain real numeric coordinates') from error
    if shape is not None and result.shape != shape:
        raise ValueError(name + ' has the wrong shape')
    if not np.isfinite(result).all():
        raise ValueError(name + ' must contain finite coordinates')
    return result


def _points(value, name, *, allow_empty=True, copy=False):
    result = _array(value, name)
    if result.shape == (0,):
        result = result.reshape(0, 3)
    if result.ndim != 2 or result.shape[1] != 3:
        raise ValueError(name + ' must have shape (N, 3)')
    if not allow_empty and not len(result):
        raise ValueError(name + ' must not be empty')
    return result.copy() if copy else result


def _band(value, name, *, distance=False):
    if value is None:
        return None
    if (not isinstance(value, (list, tuple, np.ndarray))
            or (isinstance(value, np.ndarray) and value.ndim != 1) or len(value) != 2):
        raise ValueError(name + ' must contain two increasing limits')
    lower, upper = (_number(value[0], name), _number(value[1], name))
    if lower >= upper or (distance and lower < 0):
        raise ValueError(name + ' must contain two increasing limits')
    return lower, upper


def _smooth_unit(value):
    t = np.clip(value, 0.0, 1.0)
    return t*t*(3.0-2.0*t), 6.0*t*(1.0-t)


def _fingerprint(array):
    return hashlib.sha256(np.ascontiguousarray(array, dtype='<f8').tobytes()).hexdigest()


@dataclass(frozen=True)
class FlowResult:
    positions: np.ndarray
    jacobians: np.ndarray
    report: dict


def euler_flow(velocity: Callable, query, *, steps=64, duration=1.0, start_time=0.0,
               time_sample_fraction=0.0):
    """Integrate a callable returning (velocity, spatial derivative) at time t.

    Euler updates compose as J[n+1] = (I + dt Dv(q[n], t[n])) J[n].
    The derivative must have shape (N, 3, 3), with velocity/output component
    first and query/input component second. ``duration`` is an authoring
    integration interval, not a physical simulation duration.
    ``time_sample_fraction`` chooses the time within each interval; positions
    are still evaluated at the beginning-of-step query. A value of .5 is not
    a midpoint Runge-Kutta spatial integration rule.
    """
    if not callable(velocity):
        raise ValueError('velocity must be callable')
    if isinstance(steps, (bool, np.bool_)) or not isinstance(steps, (int, np.integer)) or steps <= 0:
        raise ValueError('steps must be a positive integer')
    duration = _number(duration, 'duration')
    start_time = _number(start_time, 'start_time')
    time_sample_fraction = _number(time_sample_fraction, 'time_sample_fraction')
    if not 0 <= time_sample_fraction <= 1:
        raise ValueError('time_sample_fraction must lie between zero and one')
    if duration <= 0 or not math.isfinite(start_time + duration):
        raise ValueError('duration must be positive with a finite end time')
    q = _points(query, 'query', copy=True)
    jacobians = np.broadcast_to(np.eye(3), (len(q), 3, 3)).copy()
    minimum_sampled = 1.0 if len(q) else None
    minimum_step = None
    maximum_derivative_norm = 0.0
    maximum_displacement = 0.0
    evaluated_steps = 0
    dt = duration / int(steps)
    if dt == 0:
        raise ValueError('Euler step duration underflowed to zero')
    if len(q) and duration:
        for step in range(int(steps)):
            values = velocity(q, time=start_time + (step+time_sample_fraction)*dt)
            if not isinstance(values, (tuple, list)) or len(values) != 2:
                raise ValueError('velocity must return values and spatial derivatives')
            v = _array(values[0], 'velocity values', (len(q), 3))
            derivative = _array(values[1], 'velocity derivatives', (len(q), 3, 3))
            with np.errstate(over='ignore', invalid='ignore'):
                derivative_step = derivative*dt
                update = np.eye(3) + derivative_step
                jacobians = np.einsum('nij,njk->nik', update, jacobians)
                displacement = v*dt
                # Leave exact zero-velocity coordinates untouched, including
                # signed zeros in protected source positions.
                moved = np.any(displacement != 0, axis=1)
                q[moved] += displacement[moved]
                determinants = np.linalg.det(jacobians)
                step_determinants = np.linalg.det(update)
                derivative_norm = float(np.linalg.norm(derivative_step, axis=(1, 2)).max())
                displacement_norm = float(np.linalg.norm(displacement, axis=1).max())
            if (not np.isfinite(q).all() or not np.isfinite(jacobians).all()
                    or not np.isfinite(determinants).all() or not np.isfinite(step_determinants).all()
                    or not math.isfinite(derivative_norm) or not math.isfinite(displacement_norm)):
                raise ValueError('Euler integration produced nonfinite numerical data')
            minimum_sampled = min(minimum_sampled, float(determinants.min()))
            step_minimum = float(step_determinants.min())
            minimum_step = step_minimum if minimum_step is None else min(minimum_step, step_minimum)
            maximum_derivative_norm = max(maximum_derivative_norm, derivative_norm)
            maximum_displacement = max(maximum_displacement, displacement_norm)
            evaluated_steps += 1
    final_minimum = float(np.linalg.det(jacobians).min()) if len(q) else None
    report = {
        'algorithm':VERSION, 'point_count':len(q), 'steps':int(steps),
        'evaluated_steps':evaluated_steps, 'start_time':start_time, 'duration':duration,
        'time_sample_fraction':time_sample_fraction,
        'minimum_jacobian_determinant':final_minimum,
        'minimum_sampled_flow_jacobian_determinant':minimum_sampled,
        'sampled_flow_determinant_definition':'minimum over initial identity and all sampled composed Euler steps',
        'minimum_sampled_step_jacobian_determinant':minimum_step,
        'maximum_sampled_step_derivative_norm':maximum_derivative_norm,
        'step_derivative_norm_definition':'Frobenius norm of dt times the spatial velocity derivative at sampled points',
        'maximum_sampled_step_displacement':maximum_displacement,
        'scope':'sampled Euler map; not a global injectivity or surface-intersection proof; no runtime physics',
    }
    return FlowResult(q, jacobians, report)


class CompactVelocityField:
    """Normalized Wendland-C2 velocities with optional spatial protection gates.

    At distance d < radius, w = (1-d/r)^4 (4d/r+1). The field is
    sum(w*control_velocity) / (sum(w)+stabilizer). A strictly positive
    stabilizer brings values and derivatives continuously to zero at support.

    ``lower_y=(a,b)`` fades from zero at/below a to one at/above b;
    ``upper_y=(a,b)`` fades from one at/below a to zero at/above b.
    All mask defaults are None. With boundary points, explicitly supply
    ``boundary_band=(locked_distance, fully_active_distance)`` in source units.
    Its nearest-point distance is piecewise differentiable; the reported
    derivative chooses the nearest point at equal-distance ties.

    ``moving_centres=True`` is an experimental option: centres are p+t*v,
    while their control velocities remain unchanged. It is not enabled by
    default and carries no shape-quality or collision acceptance claim.
    """
    def __init__(self, control_points, velocities, radius, *, stabilizer=.05,
                 boundary_points=None, boundary_band=None, lower_y=None,
                 upper_y=None, moving_centres=False):
        self._controls = _points(control_points, 'control_points', allow_empty=False, copy=True)
        self._velocities = _points(velocities, 'velocities', allow_empty=False, copy=True)
        if self._controls.shape != self._velocities.shape:
            raise ValueError('Control points and velocities must have matching shapes')
        self._radius = _number(radius, 'radius')
        self._stabilizer = _number(stabilizer, 'stabilizer')
        if self._radius <= 0 or self._stabilizer <= 0:
            raise ValueError('radius and stabilizer must be positive')
        if type(moving_centres) is not bool:
            raise ValueError('moving_centres must be a boolean')
        self._moving_centres = moving_centres
        self._lower_y = _band(lower_y, 'lower_y')
        self._upper_y = _band(upper_y, 'upper_y')
        self._boundary_band = _band(boundary_band, 'boundary_band', distance=True)
        self._boundary = None
        if boundary_points is not None:
            self._boundary = _points(boundary_points, 'boundary_points', allow_empty=False, copy=True)
            if self._boundary_band is None:
                raise ValueError('Boundary points require an explicit boundary_band')
        elif self._boundary_band is not None:
            raise ValueError('boundary_band requires boundary_points')
        self._tree = cKDTree(self._controls, copy_data=True)
        self._boundary_tree = cKDTree(self._boundary, copy_data=True) if self._boundary is not None else None
        self._controls.setflags(write=False)
        self._velocities.setflags(write=False)
        if self._boundary is not None:
            self._boundary.setflags(write=False)

    @property
    def configuration(self):
        return {
            'version':VERSION, 'radius':self._radius, 'stabilizer':self._stabilizer,
            'control_count':len(self._controls), 'control_points_sha256':_fingerprint(self._controls),
            'velocities_sha256':_fingerprint(self._velocities),
            'boundary_count':len(self._boundary) if self._boundary is not None else 0,
            'boundary_points_sha256':_fingerprint(self._boundary) if self._boundary is not None else None,
            'boundary_band':list(self._boundary_band) if self._boundary_band else None,
            'lower_y':list(self._lower_y) if self._lower_y else None,
            'upper_y':list(self._upper_y) if self._upper_y else None,
            'experimental_moving_centres':self._moving_centres,
        }

    def _gate(self, query):
        gate = np.ones(len(query))
        gradient = np.zeros_like(query)
        for band, upper in ((self._lower_y, False), (self._upper_y, True)):
            if band is None:
                continue
            lower, higher = band
            factor, slope = _smooth_unit(((higher-query[:, 1]) if upper else (query[:, 1]-lower))/(higher-lower))
            factor_gradient = np.zeros_like(query)
            factor_gradient[:, 1] = slope/(higher-lower)*(-1 if upper else 1)
            gradient = gradient*factor[:, None] + gate[:, None]*factor_gradient
            gate *= factor
        if self._boundary_tree is not None:
            distance, index = self._boundary_tree.query(query)
            lower, upper = self._boundary_band
            factor, slope = _smooth_unit((distance-lower)/(upper-lower))
            factor_gradient = ((slope/(upper-lower))[:, None]
                               * (query-self._boundary[index])/np.maximum(distance[:, None], 1e-30))
            gradient = gradient*factor[:, None] + gate[:, None]*factor_gradient
            gate *= factor
        return gate, gradient

    def evaluate(self, query, *, time=0.0):
        """Return velocity and analytic spatial derivative at the given queries."""
        points = _points(query, 'query')
        time = _number(time, 'time')
        if not len(points):
            return np.zeros((0, 3)), np.zeros((0, 3, 3))
        controls = self._controls
        tree = self._tree
        if self._moving_centres:
            controls = self._controls + time*self._velocities
            if not np.isfinite(controls).all():
                raise ValueError('Moving centres produced nonfinite coordinates')
            tree = cKDTree(controls)
        near = cKDTree(points).sparse_distance_matrix(tree, self._radius, output_type='coo_matrix')
        offset = points[near.row]-controls[near.col]
        u = np.clip(near.data/self._radius, 0.0, 1.0)
        weight = (1-u)**4*(4*u+1)
        kernel_gradient = (-20/self._radius)*(1-u[:, None])**3*(offset/self._radius)
        denominator = np.bincount(near.row, weights=weight, minlength=len(points)) + self._stabilizer
        numerator = np.column_stack([
            np.bincount(near.row, weights=weight*self._velocities[near.col, axis], minlength=len(points))
            for axis in range(3)])
        denominator_gradient = np.column_stack([
            np.bincount(near.row, weights=kernel_gradient[:, axis], minlength=len(points))
            for axis in range(3)])
        numerator_derivative = np.empty((len(points), 3, 3))
        for output in range(3):
            for axis in range(3):
                numerator_derivative[:, output, axis] = np.bincount(
                    near.row, weights=kernel_gradient[:, axis]*self._velocities[near.col, output],
                    minlength=len(points))
        value = numerator/denominator[:, None]
        derivative = (numerator_derivative-value[:, :, None]*denominator_gradient[:, None, :])/denominator[:, None, None]
        gate, gate_gradient = self._gate(points)
        result = value*gate[:, None]
        derivative = derivative*gate[:, None, None] + value[:, :, None]*gate_gradient[:, None, :]
        if not np.isfinite(result).all() or not np.isfinite(derivative).all():
            raise ValueError('Field evaluation produced nonfinite numerical data')
        return result, derivative

    def flow(self, query, *, steps=64, duration=1.0, start_time=0.0, time_sample_fraction=0.0):
        result = euler_flow(self.evaluate, query, steps=steps, duration=duration, start_time=start_time,
                            time_sample_fraction=time_sample_fraction)
        return FlowResult(result.positions, result.jacobians,
                          {**result.report, 'field':self.configuration})
