import math
from datetime import datetime
from pathlib import Path

from ezdxf import bbox, edgeminer, edgesmith, transform
from ezdxf.entities.lwpolyline import LWPolyline
from ezdxf.entities.polyline import Polyline
from ezdxf.filemanagement import readfile
from ezdxf.groupby import groupby
from ezdxf.lldxf.const import DXFError, DXFStructureError
from ezdxf.math import Matrix44, Vec2, is_point_in_polygon_2d
from ezdxf.path import Path as ezPath
from ezdxf.path import make_path
from shapely import BufferJoinStyle
from shapely.geometry import MultiPolygon, Polygon

epsilon = 1e-6
join_style = BufferJoinStyle.round # round, mitre, or bevel


class ToPaths:
    def __init__(
        self, units='metric', gap_tolerance=0.01, lead_type='line', lead_length=5.0, lead_angle=45.0, flattening_distance=0.1):
        self.units = units
        self.gap_tolerance = gap_tolerance
        self.lead_type = lead_type
        self.lead_length = lead_length
        self.lead_angle = lead_angle
        self.flattening_distance = flattening_distance
        self.doc = None
        self.layers = []
        self.paths = {}
        self.sequences = {}
        self.size = (0.0, 0.0)
        self.error = None

    def reset(self):
        ''' clear previous file state before loading a new dxf '''
        self.doc = None
        self.layers = []
        self.paths = {}
        self.sequences = {}
        self.size = (0.0, 0.0)
        self.error = None

    def get_paths(self, dxf_file):
        ''' load a dxf file, convert entities to paths, and build cut sequences '''
        self.reset()
        self._open_doc(dxf_file)
        if self.doc and not self.error:
            self.layers = [
                layer.dxf.name
                for layer in self.doc.layers
                if layer.dxf.name != 'Defpoints'
            ]
            self._dxf_to_paths()
            for layer in self.layers:
                self.sequences[layer] = {
                    'cut': [],
                    'start': {},
                    'external': {},
                    'lead-in': {},
                }
                for n in self.paths[layer]:
                    self.sequences[layer]['cut'].append(n)
                    # circles start at 0 degrees; lines start at segment 0
                    self.sequences[layer]['start'][n] = 0
                    self.sequences[layer]['external'][n] = False
                    self.sequences[layer]['lead-in'][n] = {
                        'type': self.lead_type,
                        'length': self.lead_length,
                        'angle': self.lead_angle,
                        'valid': True,
                    }
            self._set_external_paths()
        return self.doc, self.layers, self.paths, self.sequences, self.size, self.error

    def _open_doc(self, dxf_file):
        ''' open a dxf file '''
        try:
            self.doc = readfile(dxf_file)
        except OSError:
            self.error = 'Not a DXF file or a generic I/O error.'
        except DXFStructureError:
            self.error = 'Invalid or corrupted DXF file.'
        except DXFError as e:
            self.error = f'\n{e}\nWhile attempting to open dxf_file\n'

    def _dxf_to_paths(self):
        ''' scale geometry, centre at origin, and chain entities into paths '''
        if self.doc is None: return
        scale = 1
        mu = self.doc.header.get('$MEASUREMENT', None)
        iu = self.doc.header.get('$INSUNITS', None)
        # metric dxf
        if mu == 1 or iu in [4, 5, 6, 7, 12, 13, 14, 15, 16]:
            scale = 1 if self.units == 'metric' else 1 / 25.4
        # imperial DXF
        elif mu == 0 or iu in [1, 2, 3, 8, 9, 10]:
            scale = 25.4 if self.units == 'metric' else 1
        # rescale if required
        if scale != 1:
            matrix = Matrix44.scale(scale)
            transform.inplace(self.doc.modelspace(), matrix)
        # get extents
        msp = self.doc.modelspace()
        bb = bbox.extents(msp)
        if bb.has_data:
            self.size = (round(bb.size.x, 2), round(bb.size.y, 2))
        # move bounding box to origin
        matrix = Matrix44.translate(bb.extmin[0] / -2, bb.extmin[1] / -2, 0)
        transform.inplace(self.doc.modelspace(), matrix)
        for block in self.doc.blocks:
            if not block.is_any_paperspace:
                transform.inplace(block, matrix)
        # get entities
        msp = self.doc.modelspace()
        entities_by_layer = groupby(
            entities=msp.query('LINE SPLINE LWPOLYLINE POLYLINE ARC CIRCLE'),
            dxfattrib='layer',
        )
        # store entities by layer
        for layer in self.layers:
            self.paths[layer] = {}
            layer_entities = entities_by_layer.get(layer, [])
            lines = [e for e in layer_entities if e.dxftype() == 'LINE']
            splines = [e for e in layer_entities if e.dxftype() == 'SPLINE']
            polylines = [e for e in layer_entities if e.dxftype() in ('LWPOLYLINE', 'POLYLINE')]
            arcs = [e for e in layer_entities if e.dxftype() == 'ARC']
            circles = [e for e in layer_entities if e.dxftype() == 'CIRCLE']
            # get edges
            edges = []
            edges.extend(
                edgesmith.edges_from_entities_2d(lines, gap_tol=self.gap_tolerance)
            )
            edges.extend(
                edgesmith.edges_from_entities_2d(splines, gap_tol=self.gap_tolerance)
            )
            for polyline in polylines:
                if isinstance(polyline, (LWPolyline, Polyline)):
                    edges.extend(
                        edgesmith.edges_from_entities_2d(
                            polyline.explode(), gap_tol=self.gap_tolerance
                        )
                    )
            for entity in arcs:
                edge = edgesmith.make_edge_2d(entity)
                if edge is not None:
                    edges.append(edge)
            # get all edge chains
            if edges:
                deposit = edgeminer.Deposit(edges, gap_tol=self.gap_tolerance)
                chains = edgeminer.find_all_simple_chains(deposit)
                # make a path from each chain
                for n, chain in enumerate(chains):
                    path = ezPath()
                    for edge in chain:
                        entity = edge.payload
                        if entity:
                            entity_path = make_path(entity)
                            if edge.is_reverse:
                                entity_path = entity_path.reversed()
                            if len(path) == 0:
                                path = entity_path
                            else:
                                path.append_path(entity_path)
                    self.paths[layer][n] = path
            # process circles
            start = len(self.paths[layer]) - 1
            for n, circle in enumerate(circles):
                self.paths[layer][start + n + 1] = {'cp': circle.dxf.center, 'r': circle.dxf.radius}

    def _set_external_paths(self):
        ''' identify outer contours vs nested internal cutouts '''
        for layer in self.layers:
            polygons = {}
            for key, path in self.paths[layer].items():
                if isinstance(path, dict): # rough diamond to imitate circles
                    vertices = [Vec2(path['cp'][0]-path['r'], path['cp'][1])]
                    vertices.append(Vec2(path['cp'][0], path['cp'][1]+path['r']))
                    vertices.append(Vec2(path['cp'][0]+path['r'], path['cp'][1]))
                    vertices.append(Vec2(path['cp'][0], path['cp'][1]-path['r']))
                else:
                    vertices = list(path.flattening(distance=self.flattening_distance))
                polygons[key] = [Vec2(v) for v in vertices]
            external_cuts = []
            # check each path to see if it is nested inside any other path
            for key, poly in polygons.items():
                # if a path has no vertices
                if not poly:
                    continue
                # get the first vertex to test for containment
                test_point = poly[0]
                is_nested = False
                for other_key, other_poly in polygons.items():
                    if key == other_key:
                        continue
                    # test if nested
                    if is_point_in_polygon_2d(test_point, other_poly) == 1:
                        is_nested = True
                        break  # it is a inner path, skip to the next one
                # if not nested then it is an outer shape
                if not is_nested:
                    external_cuts.append(key)
            # set external cuts and do them last
            for cut in external_cuts:
                print(external_cuts, cut)
                self.sequences[layer]['cut'].remove(cut)
                self.sequences[layer]['cut'].append(cut)
                self.sequences[layer]['external'][cut] = True


class ToPoints:
    def __init__(self, paths, layers, sequences, kerf, precision, small_hole, last_cut, lead_angle, flattening_distance):
        self.paths = paths
        self.layers = layers
        self.sequences = sequences
        self.kerf = kerf
        self.precision = precision
        self.small_hole = small_hole
        self.last_cut = last_cut
        self.lead_angle = lead_angle
        self.flattening_distance = flattening_distance

    def get_points(self, mode):
        cut = mode == 'cut'
        points = {}
        last_cut = (0.0, 0.0)
        warnings = []
        print(f'mode={mode}  layers={self.layers}')
        for layer in self.layers:
            points[layer] = {}
            for n in self.sequences[layer]['cut']:
                points[layer][n], last_cut, warnings_in = self._path_to_points(cut, self.paths[layer][n], layer, n, last_cut)
                warnings.extend(warnings_in)

        return points, warnings

    def _path_to_points(self, cut, path, layer, path_num, last_cut):
        external_cut = self.sequences[layer]['external'][path_num]
        offset = float(self.kerf) / 2 if external_cut else float(self.kerf) / -2
        l_length = self.sequences[layer]['lead-in'][path_num]['length']
        l_angle = self.sequences[layer]['lead-in'][path_num]['angle']
        arc_lead = self.sequences[layer]['lead-in'][path_num]['type'] == 'arc'
        points_dict = {}
        warnings = []
        # circles
        if isinstance(path, dict):
            # circle center point
            xc = round(path['cp'][0], self.precision)
            yc = round(path['cp'][1], self.precision)
            # cut path
            if cut:
                    # base angle for lead-ins
                ang = self.sequences[layer]['start'][path_num]
                # set radius to cut path rather than shape
                r = round(path['r'], self.precision) + offset
                # lead-in cannot be greater than radius
                ll = min(l_length, r)
                # external is clockwise
                g = 2 if external_cut else 3
                lg = 3
                # circle start point
                xs = xc + r * math.cos(math.radians(ang))
                ys = yc + r * math.sin(math.radians(ang))
                # small internal hole
                if r < self.small_hole / 2 and not external_cut:
                    # leadin start
                    xl = xs - ll * math.cos(math.radians(ang))
                    yl = ys - ll * math.sin(math.radians(ang))
                    # write points
                    points_dict[0] = {'seg': 0, 'start': last_cut, 'end': (xl, yl)}
                    points_dict[1] = {'seg': 1, 'start': (xl, yl), 'end': (xs, ys)}
                    points_dict[2] = {'seg': 2, 'start': (xs, ys), 'end': (xs, ys), 'cp': (xc, yc), 'r': r, 'g': g}
                    self.sequences[layer]['lead-in'][path_num]['type'] = 'line'
                else:
                    # get radius for correct lead-in length
                    lr = 2 * ll / math.pi
                    # angle from circle center to arc lead-in center
                    lead_center_angle = ang if external_cut else 180 + ang
                    # angle from arc lead-in center to arc lead-in start
                    lead_start_angle = 90 + ang if external_cut else 270 + ang
                    # lead-in center point
                    lead_cp_x = xs + lr * math.cos(math.radians(lead_center_angle))
                    lead_cp_y = ys + lr  * math.sin(math.radians(lead_center_angle))
                    if arc_lead:
                        # leadin start point
                        lead_start_x = lead_cp_x + lr * math.cos(math.radians(lead_start_angle))
                        lead_start_y = lead_cp_y + lr  * math.sin(math.radians(lead_start_angle))
                    else:
                        # angle from circle start to line lead-in start
                        a = 90 + ang - l_angle if external_cut else 270 + ang - l_angle
                        # lead-in start point
                        lead_start_x = xs + l_length * math.cos(math.radians(a))
                        lead_start_y = ys + l_length * math.sin(math.radians(a))
                    # write points
                    points_dict[0] = {'seg': 0, 'start': last_cut, 'end': (lead_start_x, lead_start_y)}
                    points_dict[1] = {'seg': 1, 'start': (lead_start_x, lead_start_y), 'end': (xs, ys)}
                    if arc_lead:
                        arc_data = {'cp': (lead_cp_x, lead_cp_y), 'r': lr, 'sa': lead_start_angle, 'e': 90, 'g': lg}
                        points_dict[1].update(arc_data)
                    points_dict[2] = {'seg': 2, 'start': (xs, ys), 'end': (xs, ys), 'cp': (xc, yc), 'r': r, 'g': g}
            # shape path
            else:
                r = path['r']
                # write points
                points_dict[0] = {'seg': 0}
                points_dict[1] = {'seg': 1}
                points_dict[2] = {'seg': 2, 'start': (xc + r, yc), 'end': (xc + r, yc), 'cp': (xc, yc), 'r': r}
        # lines
        else:
            # these are to keep pyright quiet
            lxc, lyc, lsa, lr = 0.0, 0.0, 0.0, 0.0
            # create list of vertexes
            vertices = list(path.flattening(distance=self.flattening_distance))
            # offset every vertex and set cut direction if this is a closed cut
            if cut and path.is_closed:
                poly = Polygon(vertices).buffer(0)
                offset_poly: Polygon | MultiPolygon = poly.buffer(offset, join_style=join_style)
                if offset_poly.is_empty:
                    warnings.append(f'Shape {path_num} is too constricted to offset')
                    return None
                # if offset_poly.geom_type == 'Polygon':
                if isinstance(offset_poly, Polygon):
                    vertices = list(offset_poly.exterior.coords)
                # elif offset_poly.geom_type == 'MultiPolygon':
                elif isinstance(offset_poly, MultiPolygon):
                    for p in offset_poly.geoms:
                        vertices = list(p.exterior.coords)
            # set counter clockwise and internal as the default
            if not external_cut:
                vertices.reverse()
            # create list of segments, empty points at 0 and 1 to account for rapid and lead-in
            segments = [[], []]
            for n, v in enumerate(vertices):
                if n < len(vertices) - 1:
                    segments.append([v, vertices[n + 1]])
            seg_list = list(range(len(segments)))
            s_list = []
            if cut:
                idx = self.sequences[layer]['start'][path_num]
                self.sequences[layer]['lead-in'][path_num]['valid'] = True
                if idx==0:
                    default = True # use default start segment
                    idx=2
                else:
                    default = False # use custom start segment
                s1 = seg_list[:2] # first two are rapid and lead-in
                s2 = seg_list[idx:] # from index to end
                s3 = seg_list[2:idx] # from beginning to index
                s_list = s1 + s2 + s3
                if path.is_closed:
                    # these are to keep pyright quiet
                    xs, ys, xm, ym, lxs, lys = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
                    # radius for arc leadin
                    lr = 2 * l_length / math.pi
                    # offset for line leadin
                    ll = l_length * math.sin(math.radians(self.lead_angle))
                    # base offset distance
                    offset = lr if arc_lead else ll
                    # loop until leadin fits
                    while 1:
                        # segment start point
                        xs = segments[idx][0][0]
                        ys = segments[idx][0][1]
                        # segment end point
                        xe = segments[idx][1][0]
                        ye = segments[idx][1][1]
                        # segment mid point
                        xm = (xs + xe) / 2
                        ym = (ys + ye) / 2
                        # segment angle
                        ang = math.atan2(ye - ys, xe - xs)
                        # get lead-in points
                        if arc_lead:
                            # lead-in center
                            lxc = xm + lr * math.cos(ang+math.radians(90))
                            lyc = ym + lr * math.sin(ang+math.radians(90))
                            # lead-in start
                            lxs = lxc - lr * math.cos(ang)
                            lys = lyc - lr * math.sin(ang)
                            # lead-in start angle
                            lsa = math.degrees(math.atan2(lys-lyc, lxs-lxc))
                        else:
                            # lead-in start
                            lxs = xm + l_length * math.cos(ang+math.radians(180 - l_angle))
                            lys = ym + l_length * math.sin(ang+math.radians(180 - l_angle))
                        # attempt to ensure the lead-in start is:
                        #   inside the cut for an internal cut
                        #   outside the cut for an external cut
                        if default:
                            poly = Polygon(vertices)
                            o = offset * 0.95 if external_cut else offset * -0.95
                            leadin_poly: Polygon | MultiPolygon = poly.buffer(o, join_style=join_style)
                            side = -1 if external_cut else 1
                            valid = False
                            # some small shapes may be split
                            # if leadin_poly.geom_type == 'MultiPolygon':
                            if isinstance(leadin_poly, MultiPolygon):
                                polys = [geom for geom in leadin_poly.geoms]
                            else:
                                polys = [leadin_poly]
                            for poly in polys:
                                # check leadin start distance from cut
                                leadins_poly = [Vec2(x, y) for x, y in poly.exterior.coords]
                                if is_point_in_polygon_2d(Vec2(lxs, lys), leadins_poly) == side:
                                    self.sequences[layer]['start'][path_num] = idx
                                    valid = True
                                    break
                            # valid lead-in so complete the cut
                            if valid:
                                break
                            idx += 1
                            # this run didn't work
                            if idx == len(segments):
                                # less than kerf away so fail
                                if offset - float(self.kerf) < epsilon:
                                    warnings.append(f'Could not find valid lead-in for cut {path_num}')
                                    self.sequences[layer]['lead-in'][path_num]['valid'] = False
                                    idx = 2
                                    self.sequences[layer]['start'][path_num] = idx
                                    break
                                # decrease the test distance and go again
                                else:
                                    offset -= float(self.kerf)
                                    offset = max(offset, float(self.kerf))
                                    idx = 2
                        else:
                            break
                    segments[0] = [last_cut, (lxs, lys)]
                    segments[1] = [(lxs, lys), (xm, ym)]
                    segments[idx][0] = (xm, ym)
                    segments.append([(xs, ys), (xm, ym)])
                    s_list.append(len(s_list))
                else:
                    segments[0] = [last_cut, (segments[2][0][0], segments[2][0][1])]
            # add line points to the points dict
            lst = s_list if cut else seg_list
            for n, s in enumerate(lst):
                if segments[s]:
                    points_dict[n] = {'seg': s,
                                        'start': (round(segments[s][0][0], self.precision), round(segments[s][0][1], self.precision)),
                                        'end': (round(segments[s][1][0], self.precision), round(segments[s][1][1], self.precision))}
                    if cut and s == 1 and arc_lead:
                        points_dict[n]['cp'] = (round(lxc, self.precision), round(lyc, self.precision))
                        points_dict[n]['r'] = round(lr, self.precision)
                        points_dict[n]['sa'] = round(lsa, self.precision)
                        points_dict[n]['e'] = 90.0
                        points_dict[n]['g'] = 3
                else:
                    points_dict[n] = {'seg': s}
        last_cut = points_dict[len(points_dict)-1]['end']
        last_cut = (round(last_cut[0], self.precision),
                            round(last_cut[1], self.precision))
        return points_dict, last_cut, warnings


class ToGcode:
    def __init__(self, points, layers, sequences, ignored, precision):
        self.points = points
        self.layers = layers
        self.sequences = sequences
        self.ignored = ignored
        # self.small_hole = small_hole
        # self.units = units
        self.precision = precision
        # self.material = material

    def write_gcode(self, gcode_file, small_hole, units, material):
        unit = 'G21 ; units in millimeters' if units == 'metric' else 'G20 ; units in inches'
        blend = 0.1 if units == 'metric' else 0.004
        amble = (f'{unit}\n'
                    'G40 ; cancel cutter compensation\n'
                    'G49 ; cancel tool compensation\n'
                    f'G64 P{blend} ; path blending tolerance\n'
                    'G80 ; cancel canned cycle\n'
                    'G90 ; absolute positioning\n'
                    'G92.1 ; cancel G92 offsets\n'
                    'G94 ; feed rate = units per minute\n'
                    'G97 ; spindle mode = rpm')
        gcode = [f'; {Path(gcode_file).name} by dxf2PlasmaC',
                    f'; {str(datetime.now()).rsplit(':', 1)[0]}',
                    '',
                    '; configure a temporary material',
                    f'(o=0, nu={material['nu']}, na={material['na']}, ph={material['ph']}, pd={material['pd']}, ch={material['ch']}, fr={material['fr']}, kw={material['kw']})',
                    '',
                    '#<h_velocity> = 60 ; small hole velocity = 60%',
                    f'#<h_diameter> = {small_hole} ; small hole diameter',
                    '#<holes> = 1 ; reduce velocity  for small holes',
                    '',
                    f'{amble}',
                    '',
                    'F#<_hal[plasmac.cut-feed-rate]> ; set feed rate']
        for layer in self.layers:
            if layer not in self.ignored:
                for n, point in enumerate(self.sequences[layer]['cut']):
                    gcode.append(f'\n;start of layer {layer}, cut #{n + 1}')
                    gcode.extend(self._gcode_from_points(self.points[layer][point], layer, point))
        gcode.append(f'\n{amble}\nM30')
        with open(gcode_file, 'w') as f:
            _ = f.write('\n'.join(gcode))

    def _gcode_from_points(self, points, layer, point):
        print(layer, point, points)
        code = []
        # make a segment list in cut order
        raw = [p for p in points]
        s1 = raw[:2] # first two are rapid and lead-in
        s2 = raw[self.sequences[layer]['start'][point]:-1] # from cut start to second last point
        s3 = raw[2:self.sequences[layer]['start'][point]] # from beginning to cut start
        s4 = [raw[-1]] # last point
        segments = s1 + s2 + s3 + s4
        # iterate through the segments
        for s in segments:
            if 'start' not in points[s]:
                continue
            # circles
            if 'cp' in points[s]:
                i = points[s]['cp'][0] - points[s]['start'][0]
                j = points[s]['cp'][1] - points[s]['start'][1]
                code.append(f'G0{points[s]['g']}' +
                            f' X{points[s]['end'][0]:.{self.precision}f}' +
                            f' Y{points[s]['end'][1]:.{self.precision}f}' +
                            f' I{i:.{self.precision}f}' +
                            f' J{j:.{self.precision}f}')
            # lines
            else:
                cmd = 'G00' if s == 0 else 'G01'
                code.append(f'{cmd}' +
                            f' X{points[s]['end'][0]:.{self.precision}f}' +
                            f' Y{points[s]['end'][1]:.{self.precision}f}')
            if s == 0:
                code.append('M03')
        code.append('M05')
        return code
