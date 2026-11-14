from ezdxf import bbox, edgeminer, edgesmith, transform
from ezdxf.entities.lwpolyline import LWPolyline
from ezdxf.entities.polyline import Polyline
from ezdxf.filemanagement import readfile
from ezdxf.groupby import groupby
from ezdxf.lldxf.const import DXFError, DXFStructureError
from ezdxf.math import Matrix44, Vec2, is_point_in_polygon_2d
from ezdxf.path import Path, make_path


def get_paths(dxf_file, units, gap_tolerance, lead_type, lead_length, lead_angle):
    paths = {}
    sequences = {}
    layers = []
    size = (0.0, 0.0)
    doc, error = open_doc(dxf_file)
    if doc and not error:
        layers = [l.dxf.name for l in doc.layers if l.dxf.name != 'Defpoints']
        paths, size = dxf_to_paths(doc, layers, units, gap_tolerance)
        # for layer in layers:
        #     paths[layer] = self.dxf_to_paths(doc, layer, units)
        #     sequences[layer] = {'cut': [], 'start': {}, 'external': {}, 'lead-in': {}}
        for layer in layers:
            sequences[layer] = {'cut': [], 'start': {}, 'external': {}, 'lead-in': {}}
            for n in paths[layer]:
                sequences[layer]['cut'].append(n)
                # circles start at 0 degrees
                if 'cp' in paths[layer][n]:
                    sequences[layer]['start'][n] = 0
                # lines start at segment 0 unless customized
                else:
                    sequences[layer]['start'][n] = 0
                sequences[layer]['external'][n] = False
                sequences[layer]['lead-in'][n] = {'type': lead_type, 'length': lead_length, 'angle': lead_angle, 'valid': True}
    set_external_paths(layers, paths, sequences)
    return doc, layers, paths, sequences, size, error

def open_doc(dxf_file):
    doc = None
    error = None
    try:
        doc = readfile(dxf_file)
    except OSError:
        error = 'Not a DXF file or a generic I/O error.'
    except DXFStructureError:
        error = 'Invalid or corrupted DXF file.'
    except DXFError as e:
        error = f'\n{e}\nWhile attempting to open dxf_file\n'
    return doc, error

def dxf_to_paths(doc, layers, units, gap_tolerance):
    ''' get entities
        get edges
        create counter clockwise paths '''
    paths = {}
    size = (0.0, 0.0)
    # try to determine dxf units
    scale = 1
    # $MEASUREMENT (0 = imperial, 1 = metric)
    mu = doc.header.get('$MEASUREMENT', None)
    # $INSUNITS (specific units like mm, inches etc.)
    iu = doc.header.get('$INSUNITS', None)
    # probable a metric dxf
    if mu == 1 or iu in [4, 5, 6, 7, 12, 13, 14, 15, 16]:
        scale = 1 if units == 'metric' else 1 / 25.4
    # probably an imperial dxf
    elif mu == 0 or iu in [1, 2, 3, 8, 9, 10]:
        scale = 25.4 if units == 'metric' else 1
    # try an in place scale if required
    if scale != 1:
        #  scale x, y, and z axes equally
        matrix = Matrix44.scale(scale)
        # resize all geometry coordinates
        transform.inplace(doc.modelspace(), matrix)
    # get bounding box
    msp = doc.modelspace()
    bb = bbox.extents(msp)
    if bb.has_data:
        size = (round(bb.size.x, 2), round(bb.size.y, 2))
    # move bounding box to origin
    matrix = Matrix44.translate(bb.extmin[0] / -2, bb.extmin[1] / -2, 0)
    # resize all geometry coordinates
    transform.inplace(doc.modelspace(), matrix)
    for block in doc.blocks:
        if not block.is_any_paperspace:
            transform.inplace(block, matrix)
    # get drawing enities
    msp = doc.modelspace()
    entities_by_layer = groupby(entities=msp.query('LINE SPLINE LWPOLYLINE POLYLINE ARC CIRCLE'), dxfattrib='layer')
    for layer in layers:
        paths[layer] = {}
        layer_entities = entities_by_layer.get(layer, [])
        # Separate by type if needed
        lines = [e for e in layer_entities if e.dxftype() == 'LINE']
        splines = [e for e in layer_entities if e.dxftype() == 'SPLINE']
        polylines = [e for e in layer_entities if e.dxftype() in ('LWPOLYLINE', 'POLYLINE')]
        arcs = [e for e in layer_entities if e.dxftype() == 'ARC']
        circles = [e for e in layer_entities if e.dxftype() == 'CIRCLE']

        # process lines, splines, polylines, and arcs
        # lines = msp.query('LINE').filter(lambda e: e.dxf.layer == layer)
        # splines = msp.query('SPLINE').filter(lambda e: e.dxf.layer == layer)
        # polylines=msp.query('LWPOLYLINE POLYLINE').filter(lambda e: e.dxf.layer == layer)
        # arcs = msp.query('ARC').filter(lambda e: e.dxf.layer == layer)
        #create edge list
        edges = []
        # create edges from lines
        edges.extend(list(edgesmith.edges_from_entities_2d(lines, gap_tol=gap_tolerance)))
        # add edges from splines
        edges.extend(list(edgesmith.edges_from_entities_2d(splines, gap_tol=gap_tolerance)))
        # add edges from polylines
        for polyline in polylines:
            if isinstance(polyline, (LWPolyline, Polyline)):
                edges.extend(list(edgesmith.edges_from_entities_2d(polyline.explode(), gap_tol=gap_tolerance)))
        # add edges from arcs
        for entity in arcs:
            edge = edgesmith.make_edge_2d(entity)
            if edge is not None:
                edges.append(edge)
        # get all edge chains
        if edges:
            deposit = edgeminer.Deposit(edges, gap_tol=gap_tolerance)
            chains = edgeminer.find_all_simple_chains(deposit)
            # make a path from each chain
            for n, chain in enumerate(chains):
                # path = Path()
                path = Path()
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
                paths[layer][n] = path
        # process circles
        # circles = msp.query('CIRCLE').filter(lambda e: e.dxf.layer == layer)
        start = len(paths) - 1
        for n, circle in enumerate(circles):
            paths[layer][start + n + 1] = {'cp': circle.dxf.center, 'r': circle.dxf.radius}
    return paths, size

def set_external_paths(layers, paths, sequences, flattening_distance=0.1):
    for layer in layers:
        polygons = {}
        for key, path in paths[layer].items():
            if isinstance(path, dict): # rough diamond to imitate circles
                vertices = [Vec2(path['cp'][0]-path['r'], path['cp'][1])]
                vertices.append(Vec2(path['cp'][0], path['cp'][1]+path['r']))
                vertices.append(Vec2(path['cp'][0]+path['r'], path['cp'][1]))
                vertices.append(Vec2(path['cp'][0], path['cp'][1]-path['r']))
            else:
                vertices = list(path.flattening(distance=flattening_distance))
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
            sequences[layer]['cut'].remove(cut)
            sequences[layer]['cut'].append(cut)
            sequences[layer]['external'][cut] = True
