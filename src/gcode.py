from datetime import datetime
from pathlib import Path


def write_gcode(gcode_file, points, layers, sequences, ignored, small_hole, units, precision, material):
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
    for layer in layers:
        if layer not in ignored:
            for n, point in enumerate(sequences[layer]['cut']):
                gcode.append(f'\n;start of layer {layer}, cut #{n + 1}')
                gcode.extend(gcode_from_points(points[layer][point], layer, point, sequences, precision))
    gcode.append(f'\n{amble}\nM30')
    with open(gcode_file, 'w') as f:
        _ = f.write('\n'.join(gcode))

def gcode_from_points(points, layer, point, sequences, precision):
    code = []
    # make a segment list in cut order
    raw = [p for p in points]
    s1 = raw[:2] # first two are rapid and lead-in
    s2 = raw[sequences[layer]['start'][point]:-1] # from cut start to second last point
    s3 = raw[2:sequences[layer]['start'][point]] # from beginning to cut start
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
                        f' X{points[s]['end'][0]:.{precision}f}' +
                        f' Y{points[s]['end'][1]:.{precision}f}' +
                        f' I{i:.{precision}f}' +
                        f' J{j:.{precision}f}')
        # lines
        else:
            cmd = 'G00' if s == 0 else 'G01'
            code.append(f'{cmd}' +
                        f' X{points[s]['end'][0]:.{precision}f}' +
                        f' Y{points[s]['end'][1]:.{precision}f}')
        if s == 0:
            code.append('M03')
    code.append('M05')
    return code
