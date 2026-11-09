#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Phillip A Carter
# SPDX-License-Identifier: GPL-2.0-only

import math
import os
import pickle
import sys
from datetime import datetime
from pathlib import Path
from tkinter import Canvas
from tkinter import simpledialog as Sd
from tkinter.filedialog import askopenfilename as Open
from tkinter.filedialog import asksaveasfilename as Save

import ctkmessagebox2 as Msg
import customtkinter as CTk
from CTkColorPicker import AskColor as Color
from ezdxf import DXFStructureError, bbox, edgeminer, edgesmith, readfile, transform
from ezdxf.math import Vec2, is_point_in_polygon_2d
from ezdxf.path import Path as Shape
from ezdxf.path import make_path
from PIL import Image
from shapely.geometry import Polygon


def get_asset_path(relative_path: str) -> str:
    ''' resolves paths for local pixi development and compiled pyinstaller bundles '''
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

def get_popup_point(parent, window, mouse):
    xm = mouse[0]
    ym = mouse[1]
    x_min = parent.winfo_rootx()
    x_max = parent.winfo_rootx() + parent.winfo_width()
    y_max = parent.winfo_rooty() + parent.winfo_height()
    window.update_idletasks()
    w = int(window.winfo_reqwidth() / 2)
    h = int(window.winfo_reqheight())
    x = x_max - w * 2 - 8 if xm + w > x_max else x_min + 8 if xm - w < x_min else xm - w
    y = ym - h - 20 if ym + h > y_max else ym + 20
    return x, y


class PopupMenu(CTk.CTkToplevel):
    def __init__(self, master, title, options, event, color):
        super().__init__(master)
        self.overrideredirect(True)
        self.transient(master)
        self.grab_set()
        self.result = None
        label = CTk.CTkLabel(self, text=title, text_color=color)
        label.pack(padx=4, pady=4)
        for opt in options:
            btn = CTk.CTkButton(self, text=opt, command=lambda o=opt: self._on_button_click(o))
            btn.pack(padx=4, pady=4, expand=True, fill='x')
        x, y = get_popup_point(master, self, (event.x_root, event.y_root))
        self.wm_geometry(f'+{x}+{y:.0f}')
        # this seems to only work for macos
        self.attributes('-transparent', True)
        self.configure(fg_color='systemTransparent')

    def _on_button_click(self, option):
        self.result = option
        self.destroy()


class App(CTk.CTk):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.units = 'metric'
        self.units_var = CTk.StringVar()
        self.precision = 2
        self.precision_var = CTk.StringVar()
        self.lead_length = 3.3
        self.lead_angle = 45
        self.lead_type = 'line'
        self.lead_type_var = CTk.StringVar()
        self.small_hole = 0
        self.flattening_distance = 0.025
        self.gap_tolerance = 0.001
        self.canvas_color = ''
        self.rapid_color = ''
        self.cut_color_internal = ''
        self.cut_color_external = ''
        self.shape_color = ''
        self.leadin_color = ''
        self.selected_color = ''
        self.invalid_color = ''
        self.current_path = str(Path.home())
        self.prefs_file = str(Path.home() / 'dxf2plasmac.pref')
        self.material_dict = {}
        self.material_file = ''
        self.material_file_var = CTk.StringVar()
        self.material_var = CTk.StringVar()
        self.feed_r_var = CTk.StringVar()
        self.kerf_var = CTk.StringVar()
        self.cut_h_var = CTk.StringVar()
        self.pierce_h_var = CTk.StringVar()
        self.pierce_d_var = CTk.StringVar()
        self.load_preferences()


        self.script_path = Path(__file__).parent

        # # set up window
        CTk.set_default_color_theme('dark-blue') # blue, green, or dark-blue
        CTk.set_appearance_mode('dark') # light or dark
        self.minsize(760, 540)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.protocol('WM_DELETE_WINDOW', self.shutdown)
        self.title('dxf2PlasmaC')

        self.dxf_file = ''
        self.paths = {}
        self.shape_points = {}
        self.cut_points = {}
        self.sequences = {}
        self.reversed = {}
        self.last_cut = (0.0, 0.0)
        self.show_rapids = True
        self.rapid_arrow_len = 5
        # self.zoom_limits = ()
        self.canvas_size = (1, 1)
        self.canvas_last = {'scale': 1.0, 'x': 0.0, 'y': 0.0}
        self.canvas_first = {'x': 0.0, 'y': 0.0}
        self.new_file = False
        self.loaded_file = ''
        # self.canvas_tags = {}
        self.selected_item = ''
        self.mouse = (0, 0)
        self.epsilon = 1e-6
        self.gcode_file = ''
        self.mod_key = 'Command' if sys.platform == 'darwin' else 'Control'
        self.size = (0.0, 0.0)
        self.tt_delay = 0.6 # tooltip delay

        self.icon_path = get_asset_path('assets/icons')
        self.ignored = []#['0', 'centre spot', 'holes', 'open path', 'temp', 'exterior', 'Defpoints']
        self.layers = []
        self.doc = ''


        self.create_main_page()
        self.create_prefs_frame()
        self.create_main_frame()
        self.create_menu_bar()
        self.create_side_bar()
        # all widgets instantiated so apply preferences
        self.set_preferences()

        self.focus_force()

### temp for testing ########################################
        self.shapes_to_process = 333 # limit for testing    #
        # self.load_test()                                    #
    def load_test(self):                                    # noqa:
                                                            # noqa:
        self.dxf_file = 'testing/mount.dxf'                 # noqa:
        # self.dxf_file = 'testing/circles.dxf'               # noqa:
        # self.dxf_file = 'testing/butterfly.dxf'             # noqa:
        # self.dxf_file = 'testing/screen.dxf'                # noqa:
        # self.dxf_file = 'testing/deer-hideaway.dxf'         # noqa:
        # self.dxf_file = 'testing/no_inners.dxf'             # noqa:
        self.ignored = []
        self.layers = []
        self.do_paths()                                     # noqa:
        self.set_external_paths()                           # noqa:
        self.do_shapes()                                    # noqa:
        self.do_offsets()                                   # noqa:
        self.new_file = True                                # noqa:
        self.do_plot()                                      # noqa:
                                                            # noqa:
### temp for testing ########################################

    def do_paths(self):
        # print('\ndo_paths')
        self.sequences = {'cut': [], 'start': {}, 'external': {}, 'lead-in': {}}
        # self.paths = self.dxf_to_paths(self.dxf_file)
        self.doc = self.open_doc(self.dxf_file)
        self.paths = self.dxf_to_paths(self.doc)


        for n in self.paths:
            self.sequences['cut'].append(n)
            # circles start at 0 degrees
            if 'cp' in self.paths[n]:
                self.sequences['start'][n] = 0
            # lines start at segment 0 unless customized
            else:
                self.sequences['start'][n] = 0
            self.sequences['external'][n] = False
            self.sequences['lead-in'][n] = {'type': self.lead_type, 'length': self.lead_length, 'angle': self.lead_angle, 'valid': True}

    def do_shapes(self):
        # print('\ndo_shapes')
        self.last_cut = (0.0, 0.0)
        for n in self.sequences['cut']:
            self.shape_points[n] = self.path_to_points(self.paths[n], n)

    def do_offsets(self):
        # print('\ndo_offsets')
        self.last_cut = (0.0, 0.0)
        for n in self.sequences['cut']:
            self.cut_points[n] = self.path_to_points(self.paths[n], n, True)

    def do_plot(self):
        # print('\ndo_plot shape')
        self.plot(self.shape_points, clear=True)
        # print('\ndo_plot cut')
        self.plot(self.cut_points, mode='cut', clear=False)
        self.update()
        if self.canvas.winfo_ismapped():
            if self.new_file:
                self.zoom_all()
                self.new_file = False
#FIXME first zoom doesn't hold very well ???
                self.zoom_all()
            else:
                self.canvas.scale('all', 0, 0, self.canvas_last['scale'], self.canvas_last['scale'])
                self.canvas.move('all', self.canvas_last['x'], self.canvas_last['y'])

    def do_gcode(self):
        # print('\ndo_gcode')
        nu = self.material_var.get().split(':')[0].strip() if self.material_var.get() else 0
        na = self.material_var.get().split(':')[1].strip() if self.material_var.get() else 'default'
        ph = self.pierce_h_var.get()
        pd = self.pierce_d_var.get()
        ch = self.cut_h_var.get()
        fr = self.feed_r_var.get()
        kw = self.kerf_var.get()

        print(self.material_var.get())


        units = 'G21 ; units in millimeters' if self.units == 'metric' else 'G201 ; units in inches'
        blend = 0.1 if self.units == 'metric' else 0.004
        amble = (f'{units}\n'
                 'G40 ; cancel cutter compensation\n'
                 'G49 ; cancel tool compensation\n'
                 f'G64 P{blend} ; path blending tolerance\n'
                 'G80 ; cancel canned cycle\n'
                 'G90 ; absolute positioning\n'
                 'G92.1 ; cancel G92 offsets\n'
                 'G94 ; feed rate = units per minute\n'
                 'G97 ; spindle mode = rpm')


        gcode = [f'; {Path(self.gcode_file).name} from {Path(self.dxf_file).name} by dxf2PlasmaC',
                 f'; {str(datetime.now()).rsplit(':', 1)[0]}',
                 '',
                 '; configure a temporary material',
                 f'(o=0, nu={nu}, na={na}, ph={ph}, pd={pd}, ch={ch}, fr={fr}, kw={kw})',
                 '',
                 '#<h_velocity> = 60 ; small hole velocity = 60%',
                 f'#<h_diameter> = {self.small_hole} ; small hole diameter',
                 '#<holes> = 1 ; reduce velocity  for small holes',
                 '',
                 f'{amble}',
                 '',
                 'F#<_hal[plasmac.cut-feed-rate]> ; set feed rate']


        for n, point in enumerate(self.sequences['cut']):
            gcode.append(f'\n;start of cut #{n + 1}')
            gcode.extend(self.gcode_from_points(self.cut_points[point], point))
        gcode.append(f'\n{amble}\nM30')

        for r in range(5):
            print(gcode[r])

        return gcode

    def open_doc(self, dxf_filename):
        title='File Error'
        try:
            doc = readfile(dxf_filename)
        except OSError:
            message='Not a DXF file or a generic I/O error.'
            Msg.showerror(self, title, message)
            sys.exit(1)
        except DXFStructureError:
            message='Invalid or corrupted DXF file.'
            Msg.showerror(self, title, message)
            sys.exit(2)
        except Exception as e:
            message = f'\n{e}\nWhile attempting to open dxf_filename\n'
            Msg.showerror(self, title, message)
            sys.exit(2)
        return doc

    # def dxf_to_paths(self, dxf_filename):
    def dxf_to_paths(self, doc):
        ''' get entities
            get edges
            create counter clockwise paths '''
        paths = {}
        # title='File Error'
        # # load data
        # try:
        #     doc = readfile(dxf_filename)
        # except OSError:
        #     message='Not a DXF file or a generic I/O error.'
        #     Msg.showerror(self, title, message)
        #     sys.exit(1)
        # except DXFStructureError:
        #     message='Invalid or corrupted DXF file.'
        #     Msg.showerror(self, title, message)
        #     sys.exit(2)
        # except Exception as e:
        #     message = f'\n{e}\nWhile attempting to open dxf_filename\n'
        #     Msg.showerror(self, title, message)
        #     sys.exit(2)
        # get layers
        if not self.layers:
            self.layers = [l.dxf.name for l in doc.layers]
            self.set_layers()
        # try to determine dxf units
        scale = 1
        # $MEASUREMENT (0 = imperial, 1 = metric)
        mu = doc.header.get('$MEASUREMENT', None)
        # $INSUNITS (specific units like mm, inches etc.)
        iu = doc.header.get('$INSUNITS', None)
        # probable a metric dxf
        if mu == 1 or iu in [4, 5, 6, 7, 12, 13, 14, 15, 16]:
            scale = 1 if self.units == 'metric' else 1 / 25.4
        # probably an imperial dxf
        elif mu == 0 or iu in [1, 2, 3, 8, 9, 10]:
            scale = 25.4 if self.units == 'metric' else 1
        # try an in place scale if required
        if scale != 1:
            #  scale x, y, and z axes equally
            matrix = transform.Matrix44.scale(scale)
            # resize all geometry coordinates
            transform.inplace(doc.modelspace(), matrix)
        # get bounding box
        msp = doc.modelspace()
        bb = bbox.extents(msp)
        if bb.has_data:
            self.size = (round(bb.size.x, 2), round(bb.size.y, 2))
            post = 'mm' if self.units == 'metric' else 'in'
            self.title(f'{self.title()}     Size: {self.size[0]}{post} x {self.size[1]}{post}')
        # move bounding box to origin
        matrix = transform.Matrix44.translate(bb.extmin[0] / -2, bb.extmin[1] / -2, 0)
        # resize all geometry coordinates
        transform.inplace(doc.modelspace(), matrix)
        for block in doc.blocks:
            if not block.is_any_paperspace:
                transform.inplace(block, matrix)
        # get drawing enities
        msp = doc.modelspace()
        # process lines, splines, polylines, and arcs
        lines = msp.query('LINE').filter(lambda e: e.dxf.layer not in self.ignored)
        splines = msp.query('SPLINE').filter(lambda e: e.dxf.layer not in self.ignored)
        polylines=msp.query('LWPOLYLINE POLYLINE').filter(lambda e: e.dxf.layer not in self.ignored)
        arcs = msp.query('ARC').filter(lambda e: e.dxf.layer not in self.ignored)
        #create edge list
        edges = []
        # create edges from lines
        edges.extend(list(edgesmith.edges_from_entities_2d(lines, gap_tol=self.gap_tolerance)))
        # add edges from splines
        edges.extend(list(edgesmith.edges_from_entities_2d(splines, gap_tol=self.gap_tolerance)))
        # add edges from polylines
        for polyline in polylines:
            edges.extend(list(edgesmith.edges_from_entities_2d(polyline.explode(), gap_tol=self.gap_tolerance)))
        # add edges from arcs
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
                if len(paths) == self.shapes_to_process:
                    break
                # path = Path()
                path = Shape()
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
                paths[n] = path
        # process circles
        circles = msp.query('CIRCLE').filter(lambda e: e.dxf.layer not in self.ignored)
        start = len(paths) - 1
        for n, circle in enumerate(circles):
            if len(paths) == self.shapes_to_process:
                break
            paths[start + n + 1] = {'cp': circle.dxf.center, 'r': circle.dxf.radius}
        return paths

    def set_layers(self):
        for widget in self.layer_frame.winfo_children():
            widget.destroy()
        # self.layers = [l.dxf.name for l in doc.layers]
        for layer in self.layers:
            if layer != 'Defpoints':
                check = CTk.CTkCheckBox(self.layer_frame, text=layer)
                if layer not in self.ignored:
                    check.select()
                check.configure(command=lambda c=check, l=layer: self.toggle_layer(l, c))
                check.pack(padx=4, pady=(0, 4), expand=True, fill='x', anchor='w')

    def set_external_paths(self):
        polygons = {}
        for key, path in self.paths.items():
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
            self.sequences['cut'].remove(cut)
            self.sequences['cut'].append(cut)
            self.sequences['external'][cut] = True
        return external_cuts

    def path_to_points(self, path, path_num, cut=False):
        external_cut = self.sequences['external'][path_num]
        offset = float(self.kerf_var.get()) / 2 if external_cut else float(self.kerf_var.get()) / -2
        l_length = self.sequences['lead-in'][path_num]['length']
        l_angle = self.sequences['lead-in'][path_num]['angle']
        arc_lead = self.sequences['lead-in'][path_num]['type'] == 'arc'
        points_dict = {}
        # circles
        if isinstance(path, dict):
            # circle center point
            xc = round(path['cp'][0], self.precision)
            yc = round(path['cp'][1], self.precision)
            # cut path
            if cut:
                 # base angle for lead-ins
                ang = self.sequences['start'][path_num]
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
                    points_dict[0] = {'seg': 0, 'start': self.last_cut, 'end': (xl, yl)}
                    points_dict[1] = {'seg': 1, 'start': (xl, yl), 'end': (xs, ys)}
                    points_dict[2] = {'seg': 2, 'start': (xs, ys), 'end': (xs, ys), 'cp': (xc, yc), 'r': r, 'g': g}
                    self.sequences['lead-in'][path_num]['type'] = 'line'
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
                    points_dict[0] = {'seg': 0, 'start': self.last_cut, 'end': (lead_start_x, lead_start_y)}
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
                offset_poly = poly.buffer(offset, join_style=1)# 1 = round, 2 = miter, 3 = bevel
                if offset_poly.is_empty:
                    title='Shape Warning'
                    message=f'Shape {path_num} is too constricted to offset'
                    Msg.showwarning(self, title, message)
                    return None
                if offset_poly.geom_type == 'Polygon':
                    vertices = list(offset_poly.exterior.coords)
                elif offset_poly.geom_type == 'MultiPolygon':
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
                idx = self.sequences['start'][path_num]
                self.sequences['lead-in'][path_num]['valid'] = True
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
                            leadin_poly = poly.buffer(o, join_style=2)
                            side = -1 if external_cut else 1
                            valid = False
                            # some small shapes may be split
                            if leadin_poly.geom_type == 'MultiPolygon':
                                polys = [geom for geom in leadin_poly.geoms]
                            else:
                                polys = [leadin_poly]
                            for poly in polys:
                                # check leadin start distance from cut
                                leadins_poly = [Vec2(x, y) for x, y in poly.exterior.coords]
                                if is_point_in_polygon_2d(Vec2(lxs, lys), leadins_poly) == side:
                                    self.sequences['start'][path_num] = idx
                                    valid = True
                                    break
                            # valid lead-in so complete the cut
                            if valid:
                                break
                            idx += 1
                            # this run didn't work
                            if idx == len(segments):
                                # less than kerf away so fail
                                if offset - float(self.kerf_var.get()) < self.epsilon:
                                    title='Lead-in Warning'
                                    message=f'Could not find valid lead-in for cut {path_num}'
                                    Msg.showwarning(self, title, message)
                                    self.sequences['lead-in'][path_num]['valid'] = False
                                    idx = 2
                                    self.sequences['start'][path_num] = idx
                                    break
                                # decrease the test distance and go again
                                else:
                                    offset -= float(self.kerf_var.get())
                                    offset = max(offset, float(self.kerf_var.get()))
                                    # print(f'cut {path_num} offset set to {offset}')
                                    idx = 2
                        else:
                            break
                    segments[0] = [self.last_cut, (lxs, lys)]
                    segments[1] = [(lxs, lys), (xm, ym)]
                    segments[idx][0] = (xm, ym)
                    segments.append([(xs, ys), (xm, ym)])
                    s_list.append(len(s_list))
                else:
                    segments[0] = [self.last_cut, (segments[2][0][0], segments[2][0][1])]
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
                        # g = 2 if self.sequences['external'][path_num] else 3
                        # points_dict[n]['g'] = g
                        points_dict[n]['g'] = 3
                        # print(points_dict[n])
                else:
                    points_dict[n] = {'seg': s}
        last_cut = points_dict[len(points_dict)-1]['end']
        self.last_cut = (round(last_cut[0], self.precision),
                         round(last_cut[1], self.precision))

        # if path_num == 3 and cut:
        #     print('\n')
        #     for point in points_dict:
        #         print(points_dict[point])
        #     print('\n')
        #     print(f'start = {self.sequences['start'][3]}')

        return points_dict

    def plot(self, points, mode:str='shape', clear:bool=False):
        ''' plot a job '''
        # the only difference between metric and inch are the origin pointer lengths
        spot = 0.5 if self.units == 'metric' else 0.02
        seq = 0
        # delete all existing objects
        if clear:
            self.canvas.delete('all')
            self.mouse = (0, 0)
        # draw origin pointers once only
        if mode == 'shape':
            self.canvas.create_arc(-spot, -spot, spot, spot, start=0, extent=90, fill='black', outline='black', state='disabled')
            self.canvas.create_arc(-spot, -spot, spot, spot, start=90, extent=90, fill='white', outline='black', state='disabled')
            self.canvas.create_arc(-spot, -spot, spot, spot, start=180, extent=90, fill='black', outline='black', state='disabled')
            self.canvas.create_arc(-spot, -spot, spot, spot, start=270, extent=90, fill='white', outline='black', state='disabled')
        # iterate through points
        for point in self.sequences['cut']:
             # shape was too small to offset
            if not points[point]:
                seq += 1
                continue
            # iterate through segments
            for segment in points[point]:
                line = points[point][segment]
                if 'start' not in line:
                    continue
                state = 'disabled' if mode != 'cut' or segment == 0 else 'normal'
                fill = (self.shape_color if mode == 'shape' else
                        self.rapid_color if segment == 0 else
                        self.leadin_color if segment == 1 else
                        self.cut_color_external if self.sequences['external'][point] else
                        self.invalid_color if not self.sequences['lead-in'][point]['valid'] else
                        self.cut_color_internal)
                tg = 'rapid' if segment == 0 else 'lead-in' if segment == 1 else 'feed'
                tags = (mode, str(seq), str(line['seg']), fill, tg)
                # get x and y, invert y
                x1 = line['start'][0]
                y1 = line['start'][1] * -1
                x2 = line['end'][0]
                y2 = line['end'][1] * -1
                # circles
                if 'cp' in line:
                    x = line['cp'][0]
                    y = line['cp'][1]
                    r = line['r']
                    if 'sa' in line:
                        a = line['sa']
                        e = line['e']
                        self.canvas.create_arc(x-r, -(y+r), x+r, -(y-r), start=a, extent=e, style='arc', outline=fill, tags=tags, state=state)
                    else:
                        if mode == 'cut':
                            self.canvas.create_oval(x-r, -(y+r), x+r, -(y-r), width=1, outline=fill, tags=tags, state=state)
                        else:
                            self.canvas.create_oval(x-r, -(y+r), x+r, -(y-r), width=1, outline=fill, tags=tags, state=state)
                # lines
                else:
                    if segment == 0:
                        midx = (x1 + x2) / 2
                        midy = (y1 + y2) / 2
                        self.canvas.create_line(x1, y1, midx, midy, width=1, fill=fill, tags=tags, state=state, dash=(5, 5), arrow='last')
                        self.canvas.create_line(midx, midy, x2, y2, width=1, fill=fill, tags=tags, state=state, dash=(5, 5))
                    else:
                        self.canvas.create_line(x1, y1, x2, y2, width=1, fill=fill, tags=tags, state=state)
            seq += 1
        if not self.show_rapids:
            self.canvas.itemconfig('rapid', state='hidden')

    def gcode_from_points(self, points, point):
        code = []
        # make a segment list in cut order
        raw = [p for p in points]
        s1 = raw[:2] # first two are rapid and lead-in
        s2 = raw[self.sequences['start'][point]:-1] # from cut start to second last point
        s3 = raw[2:self.sequences['start'][point]] # from beginning to cut start
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

    def shutdown(self):
        with open(self.prefs_file, 'r') as f:
            r = f.readlines()
        with open(self.prefs_file, 'w') as f:
            for l in r:
                if l.startswith('Last Path ='):
                    f.write(f'Last Path = {self.current_path}\n')
                elif l.startswith('Geometry ='):
                    f.write(f'Geometry = {self.geometry()}\n')
                else:
                    f.write(l)
        self.destroy()

    def show_option_popup(self, event):
        ''' display the context menu at the mouse cursor position '''
        if self.selected_item:
            tags = self.canvas.itemcget(self.selected_item, 'tags')
            seq = int(tags.split()[1])
            cut = self.sequences['cut'][int(tags.split()[1])]
            path = self.paths[self.sequences['cut'][seq]]
            segment = int(tags.split()[2])
            external_cut = self.sequences['external'][self.sequences['cut'][seq]]
            radius = path.get('r', None) if isinstance(path, dict) else None
            opts = ['', '']
            if segment == 0:
                return
            elif segment == 1:
                # add 1 so user doesn't see cut sequence #0
                title = f'Cut: #{seq + 1}   Lead-in'
                opt1 = 'Line \u2192 Arc' if self.sequences['lead-in'][cut]['type'] == 'line' else 'Arc \u2192 Line'
                if radius and radius < self.small_hole / 2 and not external_cut:
                    opts = ['Change Length']
                else:
                    opts = [opt1, 'Change Length']
                    if self.sequences['lead-in'][cut]['type'] == 'line':
                        opts.append('Change Angle')
                color = self.leadin_color


            else:
                # add 1 so user doesn't see cut sequence #0
                # title = f'Cut: #{seq + 1}   Segment: #{segment + 1}'
                title = f'Cut: #{seq + 1}   Segment: #{segment}'
                opt1 = 'External \u2192 Internal' if self.sequences['external'][cut] else 'Internal \u2192 External'
                if isinstance(path, dict): # circles
                    opts = [opt1, 'Change Cut Sequence', 'Change Start Angle']
                elif path.is_closed:
                    opts = [opt1, 'Change Cut Sequence', 'Set As Start Segment']
                else:
                    opts = ['Change Cut Sequence']
                color = self.cut_color_external if external_cut else self.cut_color_internal
            opts.append('Cancel')
            modal = PopupMenu(self, title, opts, event, color)
            self.wait_window(modal)
            match modal.result:
                case 'Line \u2192 Arc' | 'Arc \u2192 Line':
                    self.selected_item = ''
                    self.last_cut = (0.0, 0.0)
                    if self.sequences['lead-in'][cut]['type'] == 'line':
                        self.sequences['lead-in'][cut]['type'] = 'arc'
                    else:
                        self.sequences['lead-in'][cut]['type'] = 'line'
                    self.do_offsets()
                    self.do_plot()
                case 'Change Length':
                    self.color_selected(self.canvas.type(self.selected_item), False)
                    self.selected_item = ''
                    self.last_cut = (0.0, 0.0)
                    self.after(100, self.lead_in_length, cut, radius, external_cut)
                case 'Change Angle':
                    self.color_selected(self.canvas.type(self.selected_item), False)
                    self.selected_item = ''
                    self.last_cut = (0.0, 0.0)
                    self.after(100, self.lead_in_angle, cut)
                case 'Internal \u2192 External' | 'External \u2192 Internal':
                    self.sequences['external'][cut] = not self.sequences['external'][cut]
                    # self.sequences['start'][cut] = 2
                    self.selected_item = ''
                    self.last_cut = (0.0, 0.0)
                    self.do_offsets()
                    self.do_plot()
                case 'Change Cut Sequence':
                    self.color_selected(self.canvas.type(self.selected_item), False)
                    self.selected_item = ''
                    self.last_cut = (0.0, 0.0)
                    self.after(100, self.change_sequence, cut, seq)
                case 'Set As Start Segment':
                    self.selected_item = ''
                    self.last_cut = (0.0, 0.0)
                    self.sequences['start'][cut] = segment
                    self.do_offsets()
                    self.do_plot()
                case 'Change Start Angle':
                    self.color_selected(self.canvas.type(self.selected_item), False)
                    self.selected_item = ''
                    self.last_cut = (0.0, 0.0)
                    self.after(100, self.change_start_angle, cut, seq)
                case _:
                    pass
            if self.selected_item:
                self.color_selected(self.canvas.type(self.selected_item), False)
                self.selected_item = ''

    def change_sequence(self, cut, seq):
        # add 1 here so user doesn't see cut sequence #0
        mini = min(self.sequences['cut']) + 1
        maxi = max(self.sequences['cut']) + 1
        new_seq = Sd.askinteger('Cut Sequence',
                             f'Select a new cut position\nfrom {mini} to {maxi}',
                             initialvalue=seq + 1,
                             minvalue=mini,
                             maxvalue=maxi,
                             parent=self)
        if new_seq is not None and new_seq != seq + 1:
            self.sequences['cut'].remove(cut)
            self.sequences['cut'].insert(new_seq - 1, cut)
            self.do_offsets()
            self.do_plot()

    def change_start_angle(self, cut, seq):
        mini = 0
        maxi = 359
        ang = Sd.askinteger('Cut Start Angle',
                             f'Select a new start position\nfrom {mini} to {maxi}',
                             initialvalue=self.sequences['start'][cut],
                             minvalue=mini,
                             maxvalue=maxi,
                             parent=self)
        if ang is not None and ang != seq + 1:
            self.sequences['start'][cut] = ang
            self.do_offsets()
            self.do_plot()

    def lead_in_length(self, cut, radius, external_cut):
        maxi = radius if radius and radius < self.small_hole and not external_cut else 10
        length = Sd.askfloat('Lead-in Length',
                             f'Enter a new lead-in length\nfom 0 to {maxi}',
                             initialvalue=self.sequences['lead-in'][cut]['length'],
                             minvalue=0,
                             maxvalue=maxi,
                             parent=self)
        if length is not None:
            self.sequences['lead-in'][cut]['length'] = length
            self.do_offsets()
            self.do_plot()

    def lead_in_angle(self, cut):
        angle = Sd.askinteger('Lead-in Angle',
                             'Enter lead-in angle:',
                             initialvalue=self.sequences['lead-in'][cut]['angle'],
                             minvalue=10,
                             maxvalue=90,
                             parent=self)
        if angle is not None:
            self.sequences['lead-in'][cut]['angle'] = angle
            self.do_offsets()
            self.do_plot()

    def zoom_in(self, _event):
        ''' zoom from center of canvas '''
        x = self.canvas.winfo_width() / 2
        y = self.canvas.winfo_height() / 2
        scale = math.sqrt(2)
        self.canvas.scale('all', x, y, scale, scale)
        self.canvas_last['scale'] *= scale

    def zoom_out(self, _event):
        ''' zoom from center of canvas '''
        x = self.canvas.winfo_width() / 2
        y = self.canvas.winfo_height() / 2
        scale = math.sqrt(0.5)
        self.canvas.scale('all', x, y, scale, scale)
        self.canvas_last['scale'] *= scale
        self.canvas_last['x'] = x
        self.canvas_last['y'] = y

    def zoom_all(self, _event=None):
        ''' zoom to maximum for all '''
        # get the scale required for a full view
        bbox = self.canvas.bbox('all')
        if not bbox:
            return
        x_scale = (self.canvas.winfo_width() - 2) / (bbox[2] - bbox[0])
        y_scale = (self.canvas.winfo_height() - 2) / (bbox[3] - bbox[1])
        scale = min(x_scale, y_scale)
        # scale the canvas
        self.canvas.scale('all', 0, 0, scale, scale)
        # get view coordinates of bbox center after scaling
        bbox = self.canvas.bbox('all')
        x_diff = (self.canvas.winfo_width() - (bbox[2] - bbox[0])) / 2
        y_diff = (self.canvas.winfo_height() - (bbox[3] - bbox[1])) / 2
        # get the required move distances
        xMove = -bbox[0] + x_diff
        yMove = -bbox[1] + y_diff
        # move the canvas
        self.canvas.move('all', xMove, yMove)
        # store the current data
        self.canvas_last['scale'] *= scale
        if self.new_file:
            self.canvas_last['x'] = xMove
            self.canvas_last['y'] = yMove
            self.canvas_first['x'] = xMove
            self.canvas_first['y'] = yMove
        else:
            self.canvas_last['x'] = self.canvas_first['x']
            self.canvas_last['y'] = self.canvas_first['y']

    def pan_left(self, _event):
        ''' pan left 25% of canvas width '''
        self.canvas.move('all', self.canvas.winfo_width() * -0.25, 0)
        self.canvas_last['x'] += self.canvas.winfo_width() * -0.25

    def pan_right(self, _event):
        ''' pan right 25% of canvas width '''
        self.canvas.move('all', self.canvas.winfo_width() * 0.25, 0)
        self.canvas_last['x'] += self.canvas.winfo_width() * 0.25

    def pan_up(self, _event):
        ''' pan up 25% of canvas height '''
        self.canvas.move('all', 0, self.canvas.winfo_height() * -0.25)
        self.canvas_last['y'] += self.canvas.winfo_height() * -0.25

    def pan_down(self, _event):
        ''' pan down 25% of canvas height '''
        self.canvas.move('all', 0, self.canvas.winfo_height() * 0.25)
        self.canvas_last['y'] += self.canvas.winfo_height() * 0.25

    def canvas_resized(self, event):
        ''' canvas was resized so rescale contents '''
        # don't resize if first tab selection
        if self.canvas_size == (1, 1):
            self.canvas_size = (event.width, event.height)
            return
        # get the scale of the old canvas to the new canvas
        x_scale = event.width / self.canvas_size[0]
        y_scale = event.height / self.canvas_size[1]
        # try to figure a reasonable scale to use
        # not perfect but good enough for now
        if x_scale < 1 and y_scale < 1:
            scale = max(x_scale, y_scale)
        elif x_scale > 1 and y_scale > 1:
            scale = min(x_scale, y_scale)
        else:
            scale = 1
        # get the difference in center coordinates of the new canvas and the old canvase
        x_diff = (event.width - self.canvas_size[0]) / 2
        y_diff = (event.height - self.canvas_size[1]) / 2
        # scale the canvas
        self.canvas.scale('all', event.width / 2, event.height / 2, scale, scale)
        self.canvas_last['scale'] *= scale
        # move the view
        self.canvas.move('all', x_diff, y_diff)
        self.canvas_last['x'] += x_diff
        self.canvas_last['y'] += y_diff
        # save the new canvas size
        self.canvas_size = (event.width, event.height)

    def on_mouse_left_double(self, event):
        self.zoom_all(event)

    def on_mouse_left_press(self, event):
        self.mouse = (event.x, event.y)
        self.select_object(event)

    def on_mouse_drag(self, event):
        if event.x < self.mouse[0]:
            self.canvas.move('all', -10, 0)
            self.canvas_last['x'] -= 10
        elif event.x > self.mouse[0]:
            self.canvas.move('all', 10, 0)
            self.canvas_last['x'] += 10
        if event.y < self.mouse[1]:
            self.canvas.move('all', 0, -10)
            self.canvas_last['y'] -= 10
        elif event.y > self.mouse[1]:
            self.canvas.move('all', 0, 10)
            self.canvas_last['y'] += 10
        self.mouse = (event.x, event.y)

    def on_mousewheel(self, event):
        if event.num == 5 or event.delta < 0: # decrease
            scale = 1 / 1.1
        elif event.num == 4 or event.delta > 0: # increase
            scale = 1.1
        else:
            scale = 1
        self.canvas.scale('all', event.x, event.y, scale, scale)
        # x and y diffs between start and end
        x_diff = self.canvas_last['x'] - event.x
        y_diff = self.canvas_last['y'] - event.y
        # angle from coords
        ang = math.atan2(y_diff, x_diff)
        # length from coords
        len = math.sqrt(x_diff ** 2 + y_diff ** 2)
        # new coords from len and angle
        x_end = event.x + (len * scale) * math.cos(ang)
        y_end = event.y + (len * scale) * math.sin(ang)
        # store last data
        self.canvas_last['scale'] *= scale
        self.canvas_last['x'] = x_end
        self.canvas_last['y'] = y_end

    def select_object(self, event):
        # reset color on previously selected item
        if self.selected_item:
            self.color_selected(self.canvas.type(self.selected_item), False)
            self.selected_item = ''
        # return if nothing selected or origin selected
        if not self.canvas.gettags('current') or 'origin' in self.canvas.gettags('current')[0]:
            return
        # set color on selected item
        self.selected_item = self.canvas.find_closest(self.mouse[0], self.mouse[1])[0]
        self.color_selected(self.canvas.type(self.selected_item), True)
        self.show_option_popup(event)

    def color_selected(self, itemType, selected):
        if self.selected_item:
            color = self.selected_color if selected else self.canvas.itemcget(self.selected_item, 'tags').split()[3]
            if itemType == 'line':
                self.canvas.itemconfig(self.selected_item, fill=color)
            elif itemType == 'arc':
                self.canvas.itemconfig(self.selected_item, outline=color)

    def open_project(self, _event):
        file = Open(parent=self,
                    title='Open Project',
                    filetypes=[('Project File', '*.d2p'), ('Any File', '*.*')],
                    initialdir=self.current_path,
                    initialfile = self.loaded_file)
        if file:
            self.title(f'dxf2PlasmaC     project file: {Path(file).name}')
            self.current_path = str(Path(file).parent)
            with open(file, 'rb') as f:
                self.paths = pickle.load(f)
                self.cut_points = pickle.load(f)
                self.shape_points = pickle.load(f)
                self.sequences = pickle.load(f)
                self.ignored = pickle.load(f)
                self.layers = pickle.load(f)
            self.dxf_file = ''
            self.loaded_file = str(Path(file).stem)
            self.new_file = True
            self.selected_item = ''
            self.last_cut = (0.0, 0.0)
            self.set_layers()
            self.do_plot()

    def save_project(self, _event):
        file = Save(parent=self,
                    title='Save Project',
                    filetypes=[('Project File', '*.d2p'), ('Any File', '*.*')],
                    initialdir=self.current_path,
                    initialfile = self.loaded_file)
        if file:
            self.current_path = str(Path(file).parent)
            with open(file, 'wb') as f:
                pickle.dump(self.paths, f)
                pickle.dump(self.cut_points, f)
                pickle.dump(self.shape_points, f)
                pickle.dump(self.sequences, f)
                pickle.dump(self.ignored, f)
                pickle.dump(self.layers, f)

    def import_dxf(self, _event):
        self.update()
        file = Open(parent=self,
                    title='Open DXF File',
                    filetypes=[('DXF File', '.dxf'), ('Any File', '*.*')],
                    initialdir=self.current_path)
        self.update()
        if file:
            self.title(f'dxf2PlasmaC     dxf file: {Path(file).name}')
            self.current_path = str(Path(file).parent)
            self.dxf_file = file
            self.loaded_file = str(Path(file).stem)
            self.new_file = True
            self.ignored = []
            self.layers = []
            self.do_paths()
            self.set_external_paths()
            self.do_shapes()
            self.do_offsets()
            self.do_plot()

    def export_gcode(self, _event):
        file = Save(parent=self,
                    title='Save GCode File',
                    filetypes=[('GCode File', '*.ngc'), ('Any File', '*.*')],
                    initialdir=self.current_path,
                    initialfile = self.loaded_file)#self.gcode_file)
        if file:
            self.gcode_file = file
            gcode = self.do_gcode()
            with open(self.gcode_file, 'w') as f:
                print(f'self.gcode_file={self.gcode_file}')
                _ = f.write('\n'.join(gcode))

    def show_preferences_frame(self, _event):
        self.prefs_frame.lift()

    def show_materials_frame(self, _event):
        self.materials_frame.lift()

    def show_about(self, _event):
        title = 'About dxf2plasmac'
        message = 'It\'s all about me\nVersion 0.1.0'
        Msg.showinfo(self, title, message)

    def create_main_page(self):
        self.main_page = CTk.CTkFrame(self, border_width=0)
        self.main_page.pack(expand=True, fill='both')
        self.main_page.grid_rowconfigure(0, weight=1)
        self.main_page.grid_columnconfigure(0, weight=1)

    def create_main_frame(self):
        self.main_frame = CTk.CTkFrame(self.main_page, border_width=0)
        self.main_frame.grid(row=0, column=0, padx=2, pady=2, sticky='nsew')
        self.main_frame.grid_rowconfigure(1, weight=1)
        self.main_frame.grid_columnconfigure(1, weight=1)
        # canvas
        self.canvas = Canvas(self.main_frame, bg=self.canvas_color, highlightthickness=0)
        self.canvas.grid(row=1, column=1, padx=(2), pady=2, sticky='nsew')
        self.canvas.bind('<Double-Button-1>', self.on_mouse_left_double)
        self.canvas.bind('<Button-1>', self.on_mouse_left_press)
        self.canvas.bind('<B1-Motion>', self.on_mouse_drag)
        self.canvas.bind('<MouseWheel>', self.on_mousewheel)
        self.canvas.bind('<Button-4>', self.on_mousewheel)
        self.canvas.bind('<Button-5>', self.on_mousewheel)
        self.canvas.bind('<Configure>', self.canvas_resized)

        mat = CTk.CTkFrame(self.main_frame)
        mat.grid(row=2, column=0, columnspan=2, sticky='w')
        mat.grid_columnconfigure(1, weight=1)
        label_material = CTk.CTkLabel(mat, text='Material:', width=80, anchor='e')
        label_material.grid(row=0, column=0, padx=4, pady=(4, 0), sticky='ew')
        self.material_select = CTk.CTkOptionMenu(mat, width=240, variable=self.material_var, values=['None'], command=self.material_selected, anchor='w')
        self.material_select.grid(row=0, column=1, padx=4, pady=0, sticky='nsew')

    def create_menu_bar(self):
        menu = CTk.CTkFrame(self.main_frame)
        menu.grid(row=0, column=0, columnspan=2, sticky='ew')
        menu.grid_columnconfigure(8, weight=1)
        size = 36
        im = CTk.CTkImage(Image.open(f'{self.icon_path}/import_dxf.png'), size=(size, size))
        iml = CTk.CTkLabel(master = menu, image=im, width=size, height=size, bg_color='gray60', text='')
        iml.image = im
        iml.bind('<Button-1>', self.import_dxf)
        iml.grid(row=0, column=0, padx=(2, 0), pady=(2, 0))
        ex = CTk.CTkImage(Image.open(f'{self.icon_path}/export_gcode.png'), size=(size, size))
        exl = CTk.CTkLabel(master = menu, image=ex, width=size, height=size, bg_color='gray60', text='')
        exl.image = ex
        exl.bind('<Button-1>', self.export_gcode)
        exl.grid(row=0, column=1, padx=(4, 0), pady=(2, 0))
        op = CTk.CTkImage(Image.open(f'{self.icon_path}/open_project.png'), size=(size, size))
        opl = CTk.CTkLabel(master = menu, image=op, width=size, height=size, bg_color='gray60', text='')
        opl.image = op
        opl.bind('<Button-1>', self.open_project)
        opl.grid(row=0, column=2, padx=(8, 0), pady=(4, 2))
        sp = CTk.CTkImage(Image.open(f'{self.icon_path}/save_project.png'), size=(size, size))
        spl = CTk.CTkLabel(master = menu, image=sp, width=size, height=size, bg_color='gray60', text='')
        spl.image = sp
        spl.bind('<Button-1>', self.save_project)
        spl.grid(row=0, column=3, padx=(4, 0), pady=(2, 0))
        # t = CTk.CTkImage(Image.open(f'{self.icon_path}/tools.png'), size=(size, size))
        # tl = CTk.CTkLabel(master = menu, image=t, width=size, height=size, bg_color='gray60', text='')
        # tl.image = t
        # tl.bind('<Button-1>', self.show_materials_frame)
        # tl.grid(row=0, column=4, padx=(24, 0), pady=(2, 0))
        si = CTk.CTkImage(Image.open(f'{self.icon_path}/settings.png'), size=(size, size))
        sl = CTk.CTkLabel(master = menu, image=si, width=size, height=size, bg_color='gray60', text='')
        sl.image = si
        sl.bind('<Button-1>', self.show_preferences_frame)
        sl.grid(row=0, column=5, padx=(24, 0), pady=(2, 0))
        a = CTk.CTkImage(Image.open(f'{self.icon_path}/info.png'), size=(size, size))
        al = CTk.CTkLabel(master = menu, image=a, width=size, height=size, bg_color='gray60', text='')
        al.image = a        # al = CTk.CTkLabel(master = menu, image=(f'{self.icon_path}/info.png', size, size), width=size, height=size, bg_color='gray60', text='')
        al.bind('<Button-1>', self.show_about)
        al.grid(row=0, column=6, padx=(24, 0), pady=(2, 0))
        # hr = CTk.CTkImage(Image.open(f'{self.icon_path}/smiley.png'), size=(size, size))
        # hrl = CTk.CTkLabel(master = menu, image=hr, width=size, height=size, bg_color='gray60', text='')
        # hrl.image = hr
        # hrl.bind('<Button-1>', self.toggle_rapids)
        # hrl.grid(row=0, column=7, padx=(24, 0), pady=(2, 0))
        za = CTk.CTkImage(Image.open(f'{self.icon_path}/zoom_all.png'), size=(size, size))
        zal = CTk.CTkLabel(master = menu, image=za, width=size, height=size, bg_color='gray60', text='')
        zal.image = za
        zal.bind('<Button-1>', self.zoom_all)
        zal.grid(row=0, column=9, padx=(4, 0), pady=(2, 0))
        zi = CTk.CTkImage(Image.open(f'{self.icon_path}/zoom_in.png'), size=(size, size))
        zil = CTk.CTkLabel(master = menu, image=zi, width=size, height=size, bg_color='gray60', text='')
        zil.image = zi
        zil.bind('<Button-1>', self.zoom_in)
        zil.grid(row=0, column=10, padx=(8, 0), pady=(2, 0))
        zo = CTk.CTkImage(Image.open(f'{self.icon_path}/zoom_out.png'), size=(size, size))
        zol = CTk.CTkLabel(master = menu, image=zo, width=size, height=size, bg_color='gray60', text='')
        zol.image = zo
        zol.bind('<Button-1>', self.zoom_out)
        zol.grid(row=0, column=11, padx=(4, 0), pady=(2, 0))
        pl = CTk.CTkImage(Image.open(f'{self.icon_path}/pan_left.png'), size=(size, size))
        pll = CTk.CTkLabel(master = menu, image=pl, width=size, height=size, bg_color='gray60', text='')
        pll.image = pl
        pll.bind('<Button-1>', self.pan_left)
        pll.grid(row=0, column=12, padx=(8, 0), pady=(2, 0))
        pr = CTk.CTkImage(Image.open(f'{self.icon_path}/pan_right.png'), size=(size, size))
        prl = CTk.CTkLabel(master = menu, image=pr, width=size, height=size, bg_color='gray60', text='')
        prl.image = pr
        prl.bind('<Button-1>', self.pan_right)
        prl.grid(row=0, column=13, padx=(4, 0), pady=(2, 0))
        pu = CTk.CTkImage(Image.open(f'{self.icon_path}/pan_up.png'), size=(size, size))
        pul = CTk.CTkLabel(master = menu, image=pu, width=size, height=size, bg_color='gray60', text='')
        pul.image = pu
        pul.bind('<Button-1>', self.pan_up)
        pul.grid(row=0, column=14, padx=(4, 0), pady=(2, 0))
        pd = CTk.CTkImage(Image.open(f'{self.icon_path}/pan_down.png'), size=(size, size))
        pdl = CTk.CTkLabel(master = menu, image=pd, width=size, height=size, bg_color='gray60', text='')
        pdl.image = pd
        pdl.bind('<Button-1>', self.pan_down)
        pdl.grid(row=0, column=15, padx=(4, 2), pady=(2, 0))

    def create_side_bar(self):
        side = CTk.CTkFrame(self.main_frame)
        side.grid(row=1, column=0, sticky='ns')
        side.grid_rowconfigure((2, 4), weight=1)
        kerf = CTk.CTkLabel(side, text='Layers')#, anchor='w')
        kerf.grid(row=0, column=0, columnspan=2, padx=(4, 2), pady=(4, 2), sticky='new')
        self.layer_frame = CTk.CTkFrame(side, width=100, fg_color='transparent')
        self.layer_frame.grid(row=1, column=0, columnspan=2, sticky='new')

        check = CTk.CTkCheckBox(side, text='Rapids')
        check.select()
        # check.configure(command=lambda c=check, l=layer: self.toggle_layer(l, c))
        check.configure(command=self.toggle_rapids)
        check.grid(row=3, column=0, columnspan=2, padx=(4, 2), pady=(4, 2), sticky='new')

        ew = 48 # entry width
        row = 5
        kerf = CTk.CTkLabel(side, text='Kerf Width:', anchor='e')
        kerf.grid(row=row, column=0, padx=(4, 2), pady=(4, 2), sticky='nsew')
        kerf_entry = CTk.CTkEntry(side, textvariable=self.kerf_var, width=ew, border_width=1)
        kerf_entry.grid(row=row, column=1, padx=(2, 4), pady=(4, 2), sticky='nsew')
        row += 1
        feed = CTk.CTkLabel(side, text='Cut Speed:', anchor='e')
        feed.grid(row=row, column=0, padx=(4, 2), pady=2, sticky='nsew')
        feed_entry = CTk.CTkEntry(side, textvariable=self.feed_r_var, width=ew, border_width=1)
        feed_entry.grid(row=row, column=1, padx=(2, 4), pady=2, sticky='nsew')
        row += 1
        cut_h = CTk.CTkLabel(side, text='Cut Height:', anchor='e')
        cut_h.grid(row=row, column=0, padx=(4, 2), pady=2, sticky='nsew')
        cut_h_entry = CTk.CTkEntry(side, textvariable=self.cut_h_var, width=ew, border_width=1)
        cut_h_entry.grid(row=row, column=1, padx=(2, 4), pady=2, sticky='nsew')
        row += 1
        pierce_h = CTk.CTkLabel(side, text='Pierce Height:', anchor='e')
        pierce_h.grid(row=row, column=0, padx=(4, 2), pady=2, sticky='nsew')
        pierce_h_entry = CTk.CTkEntry(side, textvariable=self.pierce_h_var, width=ew, border_width=1)
        pierce_h_entry.grid(row=row, column=1, padx=(2, 4), pady=2, sticky='nsew')
        row += 1
        pierce_d = CTk.CTkLabel(side, text='Pierce Delay:', anchor='e')
        pierce_d.grid(row=row, column=0, padx=(4, 2), pady=2, sticky='nsew')
        pierce_d_entry = CTk.CTkEntry(side, textvariable=self.pierce_d_var, width=ew, border_width=1)
        pierce_d_entry.grid(row=row, column=1, padx=(2, 4), pady=2, sticky='nsew')
        if self.material_file:
            self.load_material_file()
        else:
            if self.units == 'metric':
                self.kerf_var.set(1)
                self.feed_r_var.set(1000)
                self.cut_h_var.set(1)
                self.pierce_h_var.set(3)
            else:
                self.kerf_var.set(0.04)
                self.feed_r_var.set(250)
                self.cut_h_var.set(0.04)
                self.pierce_h_var.set(0.12)
            self.pierce_d_var.set(1)

    def create_prefs_frame(self):
        # preferences frame, blank frame to cover the window
        self.prefs_frame = CTk.CTkFrame(self.main_page)
        self.prefs_frame.grid(row=0, column=0, padx=2, pady=2, sticky='nsew')
        self.prefs_frame.grid_rowconfigure(0, weight=1)
        self.prefs_frame.grid_columnconfigure(1, weight=1)
        prefs = CTk.CTkFrame(self.prefs_frame, border_width=0, fg_color='transparent')
        prefs.place(relx=0.5, rely=0.5, anchor='center')
        # button width
        bw=30
        # parameter frame
        parameters = CTk.CTkFrame(prefs, border_width=1)
        parameters.grid(row=0, column=0, padx=(0, 4), sticky='nsw')
        label_prefs = CTk.CTkLabel(parameters, text='Parameters')
        label_prefs.grid(row=0, column=0, columnspan=2, padx=4, pady=2, sticky='ew')
        units = CTk.CTkLabel(parameters, text='Units')
        units.grid(row=1, column=0, padx=4, pady=2, sticky='e')
        self.units_pref = CTk.CTkOptionMenu(parameters, variable=self.units_var, values=['metric', 'dinosaur'])
        self.units_pref.grid(row=1, column=1, padx=4, pady=2, sticky='ew')
        precision = CTk.CTkLabel(parameters, text='Precision')
        precision.grid(row=2, column=0, padx=4, pady=2, sticky='e')
        self.precision_pref = CTk.CTkOptionMenu(parameters, variable=self.precision_var, values=['2', '3', '4', '5', '6'])
        self.precision_pref.grid(row=2, column=1, padx=4, pady=2, sticky='ew')
        lead_length = CTk.CTkLabel(parameters, text='Lead-in Length')
        lead_length.grid(row=4, column=0, padx=4, pady=2, sticky='e')
        self.lead_length_pref = CTk.CTkEntry(parameters, border_width=0)
        self.lead_length_pref.grid(row=4, column=1, padx=4, pady=2, sticky='ew')
        lead_angle = CTk.CTkLabel(parameters, text='Lead-in Angle')
        lead_angle.grid(row=5, column=0, padx=4, pady=2, sticky='e')
        self.lead_angle_pref = CTk.CTkEntry(parameters, border_width=0)
        self.lead_angle_pref.grid(row=5, column=1, padx=4, pady=2, sticky='ew')
        lead_type = CTk.CTkLabel(parameters, text='Lead-in Type')
        lead_type.grid(row=6, column=0, padx=4, pady=2, sticky='e')
        self.lead_type_pref = CTk.CTkOptionMenu(parameters, variable=self.lead_type_var, values=['line', 'arc'])
        self.lead_type_pref.grid(row=6, column=1, padx=4, pady=2, sticky='ew')
        small_hole = CTk.CTkLabel(parameters, text='Small Hole Dimeter')
        small_hole.grid(row=7, column=0, padx=4, pady=2, sticky='e')
        self.small_hole_pref = CTk.CTkEntry(parameters, border_width=0)
        self.small_hole_pref.grid(row=7, column=1, padx=4, pady=2, sticky='ew')
        flattening = CTk.CTkLabel(parameters, text='Arc Flattening Distance')
        flattening.grid(row=8, column=0, padx=4, pady=2, sticky='e')
        self.flattening_pref = CTk.CTkEntry(parameters, border_width=0)
        self.flattening_pref.grid(row=8, column=1, padx=4, pady=2, sticky='ew')
        gap = CTk.CTkLabel(parameters, text='Gap Tolerance')
        gap.grid(row=9, column=0, padx=4, pady=(2, 4), sticky='e')
        self.gap_pref = CTk.CTkEntry(parameters, border_width=0)
        self.gap_pref.grid(row=9, column=1, padx=4, pady=(2, 4), sticky='ew')
        # color frame
        colors = CTk.CTkFrame(prefs, border_width=1)
        colors.grid(row=0, column=1, padx=(4, 0), sticky='nse')
        label_colors = CTk.CTkLabel(colors, text='Colors')
        label_colors.grid(row=0, column=0, columnspan=2, padx=4, pady=2, sticky='ew')
        canvas_bg = CTk.CTkLabel(colors, text='Canvas Back')
        canvas_bg.grid(row=3, column=0, padx=4, pady=2, sticky='e')
        self.canvas_bg_pref = CTk.CTkButton(colors, width=bw, command=lambda: self.set_color(self.canvas_bg_pref, canvas_bg.cget('text')))
        self.canvas_bg_pref.grid(row=3, column=1, padx=4, pady=2, sticky='nsew')
        rapid = CTk.CTkLabel(colors, text='Rapid Move')
        rapid.grid(row=4, column=0, padx=4, pady=2, sticky='e')
        self.rapid_pref = CTk.CTkButton(colors, width=bw, command=lambda: self.set_color(self.rapid_pref, rapid.cget('text')))
        self.rapid_pref.grid(row=4, column=1, padx=4, pady=2, sticky='nsew')
        internal =  CTk.CTkLabel(colors, text='Internal Cut')
        internal.grid(row=5, column=0, padx=4, pady=2, sticky='e')
        self.internal_pref = CTk.CTkButton(colors, width=bw, command=lambda: self.set_color(self.internal_pref, internal.cget('text')))
        self.internal_pref.grid(row=5, column=1, padx=4, pady=2, sticky='nsew')
        external =  CTk.CTkLabel(colors, text='External Cut')
        external.grid(row=6, column=0, padx=4, pady=2, sticky='e')
        self.external_pref = CTk.CTkButton(colors, width=bw, command=lambda: self.set_color(self.external_pref, external.cget('text')))
        self.external_pref.grid(row=6, column=1, padx=4, pady=2, sticky='nsew')
        shape =  CTk.CTkLabel(colors, text='Original Shape')
        shape.grid(row=7, column=0, padx=4, pady=2, sticky='e')
        self.shape_pref = CTk.CTkButton(colors, width=bw, command=lambda: self.set_color(self.shape_pref, shape.cget('text')))
        self.shape_pref.grid(row=7, column=1, padx=4, pady=2, sticky='nsew')
        leadin =  CTk.CTkLabel(colors, text='Lead-in')
        leadin.grid(row=8, column=0, padx=4, pady=2, sticky='e')
        self.leadin_pref = CTk.CTkButton(colors, width=bw, command=lambda: self.set_color(self.leadin_pref, leadin.cget('text')))
        self.leadin_pref.grid(row=8, column=1, padx=4, pady=2, sticky='nsew')
        selected =  CTk.CTkLabel(colors, text='Selected')
        selected.grid(row=9, column=0, padx=4, pady=2, sticky='e')
        self.selected_pref = CTk.CTkButton(colors, width=bw, command=lambda: self.set_color(self.selected_pref, selected.cget('text')))
        self.selected_pref.grid(row=9, column=1, padx=4, pady=2, sticky='nsew')
        invalid =  CTk.CTkLabel(colors, text='Invalid')
        invalid.grid(row=10, column=0, padx=4, pady=(2, 4), sticky='e')
        self.invalid_pref = CTk.CTkButton(colors, width=bw, command=lambda: self.set_color(self.invalid_pref, invalid.cget('text')))
        self.invalid_pref.grid(row=10, column=1, padx=4, pady=(2, 4), sticky='nsew')
        # material frame
        materials = CTk.CTkFrame(prefs, border_width=1)
        materials.columnconfigure(1, weight=1)
        materials.grid(row=1, column=0, columnspan=2, padx=0, pady=(16, 0), sticky='nsew')
        label_materials = CTk.CTkLabel(materials, text='Material File:')
        label_materials.grid(row=0, column=0, sticky='w', padx=4, pady=2)
        label_material_file = CTk.CTkLabel(materials, textvariable=self.material_file_var, anchor='w')#, activebackground='pink')#)
        label_material_file.bind('<Button-1>', self.set_material_file)
        label_material_file.grid(row=0, column=1, padx=4, sticky='ew')
        # action buttons
        action = CTk.CTkFrame(prefs, border_width=1)
        action.columnconfigure((0, 1, 2, 3, 4), weight=1, uniform='action')
        action.grid(row=2, column=0, columnspan=2, padx=0, pady=(16, 0), sticky='nsew')
        save = CTk.CTkButton(action, text='Save', width=bw, command=self.save_prefs)
        save.grid(row=0, column=0, padx=(4,0), pady=4, sticky='nsew')
        apply = CTk.CTkButton(action, text='Apply', width=bw, command=self.apply_prefs)
        apply.grid(row=0, column=2, pady=4, sticky='nsew')
        close = CTk.CTkButton(action, text='Close', width=bw, command=self.close_prefs)
        close.grid(row=0, column=4, padx=(0,4), pady=4, sticky='nsew')

    def set_material_file(self, _event):
        i_dir = Path(self.material_file).parent if self.material_file else self.current_path
        i_file = self.material_file_var.get()
        file = Open(parent=self,
                    title='Set Material File',
                    filetypes=[('QtPlasmaC Material File', '*.cfg'), ('Any File', '*.*')],
                    initialdir=i_dir,
                    initialfile=i_file)
        if file:
            self.material_file = file
            self.load_material_file()

    def save_prefs(self):
        self.get_preferences()
        self.save_preferences()
        # self.prefs_frame.lower()

    def apply_prefs(self):
        self.get_preferences()
        self.canvas.config(bg=self.canvas_color)
        if self.loaded_file:
            self.last_cut = (0.0, 0.0)
            self.do_offsets()
            self.do_plot()

    def close_prefs(self):
        self.prefs_frame.lower()

    def apply_materials(self):
        if self.loaded_file:
            self.last_cut = (0.0, 0.0)
            self.do_offsets()
            self.do_plot()

    def close_materials(self):
        self.materials_frame.lower()

    def toggle_layer(self, l, e):
        if e.get():
            self.ignored.remove(l)
        else:
            self.ignored.append(l)
        self.do_paths()
        self.set_external_paths()
        self.do_shapes()
        self.do_offsets()
        self.do_plot()
        self.zoom_all()

    def toggle_rapids(self):
        state = 'hidden' if self.show_rapids else 'normal'
        self.canvas.itemconfig('rapid', state=state)
        self.show_rapids = not self.show_rapids

    def set_color(self, widget, title='title'):
        color = Color(title=f'Choose A {title} Color', initial_color=widget.cget('fg_color')).get()
        if color:
            widget.configure(text=color, fg_color=color)
        self.update_idletasks()
        self.focus_force()

    def load_material_file(self):
        self.material_file_var.set(Path(self.material_file).name)
        with open(self.material_file, 'r') as f:
            materials = f.readlines()
        temp = {}
        material = 0
        for line in materials:
            if line.startswith('[MATERIAL_NUMBER_'):
                material = line.rsplit('_', 1)[1].strip().strip(']')
                temp[material] = {'NUM': material}
            elif line.startswith('NAME'):
                temp[material]['NAME'] = line.split('=')[1].strip()
            elif line.startswith('KERF_WIDTH'):
                temp[material]['KERF_WIDTH'] = line.split('=')[1].strip()
            elif line.startswith('THC'):
                temp[material]['THC'] = line.split('=')[1].strip()
            elif line.startswith('PIERCE_HEIGHT'):
                temp[material]['PIERCE_HEIGHT'] = line.split('=')[1].strip()
            elif line.startswith('PIERCE_DELAY'):
                temp[material]['PIERCE_DELAY'] = line.split('=')[1].strip()
            elif line.startswith('PUDDLE_JUMP_HEIGHT'):
                temp[material]['PUDDLE_JUMP_HEIGHT'] = line.split('=')[1].strip()
            elif line.startswith('PUDDLE_JUMP_DELAY'):
                temp[material]['PUDDLE_JUMP_DELAY'] = line.split('=')[1].strip()
            elif line.startswith('CUT_HEIGHT'):
                temp[material]['CUT_HEIGHT'] = line.split('=')[1].strip()
            elif line.startswith('CUT_SPEED'):
                temp[material]['CUT_SPEED'] = line.split('=')[1].strip()
            elif line.startswith('CUT_AMPS'):
                temp[material]['CUT_AMPS'] = line.split('=')[1].strip()
            elif line.startswith('CUT_VOLTS'):
                temp[material]['CUT_VOLTS'] = line.split('=')[1].strip()
            elif line.startswith('PAUSE_AT_END'):
                temp[material]['PAUSE_AT_END'] = line.split('=')[1].strip()
            elif line.startswith('GAS_PRESSURE'):
                temp[material]['GAS_PRESSURE'] = line.split('=')[1].strip()
            elif line.startswith('CUT_MODE'):
                temp[material]['CUT_MODE'] = line.split('=')[1].strip()
        opts = [f'{o}:  {temp[o]['NAME']}' for o in temp]
        self.material_select.configure(values=opts)
        self.material_dict = dict(sorted(temp.items()))
        self.material_selected(min(opts))

    def material_selected(self, material):
        num = material.split(':')[0].strip()
        self.material_var.set(f'{num}:  {self.material_dict[num]['NAME']}')
        self.feed_r_var.set(self.material_dict[num]['CUT_SPEED'])
        self.kerf_var.set(self.material_dict[num]['KERF_WIDTH'])
        self.pierce_h_var.set(self.material_dict[num]['PIERCE_HEIGHT'])
        self.pierce_d_var.set(self.material_dict[num]['PIERCE_DELAY'])
        self.cut_h_var.set(self.material_dict[num]['CUT_HEIGHT'])

    def get_preferences(self):
        ''' applies preference page widget values to the preference variables '''
        self.units = self.units_var.get()
        self.precision = int(self.precision_var.get())
        self.lead_length = float(self.lead_length_pref.get())
        self.lead_angle = int(self.lead_angle_pref.get())
        self.lead_type = self.lead_type_var.get()
        self.small_hole = float(self.small_hole_pref.get())
        self.flattening_distance = float(self.flattening_pref.get())
        self.gap_tolerance = float(self.gap_pref.get())
        self.canvas_color = self.canvas_bg_pref.cget('text')
        self.rapid_color = self.rapid_pref.cget('text')
        self.cut_color_internal = self.internal_pref.cget('text')
        self.cut_color_external = self.external_pref.cget('text')
        self.shape_color = self.shape_pref.cget('text')
        self.leadin_color = self.leadin_pref.cget('text')
        self.selected_color = self.selected_pref.cget('text')
        self.invalid_color = self.invalid_pref.cget('text')

    def set_preferences(self):
        ''' applies preference variable values to the preference page widgets '''
        self.units_var.set(self.units)
        self.precision_var.set(self.precision)
        self.lead_length_pref.delete(0, CTk.END)
        self.lead_length_pref.insert(0, self.lead_length)
        self.lead_angle_pref.delete(0, CTk.END)
        self.lead_angle_pref.insert(0, self.lead_angle)
        self.lead_type_var.set(self.lead_type)
        self.small_hole_pref.delete(0, CTk.END)
        self.small_hole_pref.insert(0, self.small_hole)
        self.flattening_pref.delete(0, CTk.END)
        self.flattening_pref.insert(0, self.flattening_distance)
        self.gap_pref.delete(0, CTk.END)
        self.gap_pref.insert(0, self.gap_tolerance)
        self.canvas_bg_pref.configure(text=self.canvas_color, fg_color=self.canvas_color)
        self.rapid_pref.configure(text=self.rapid_color, fg_color=self.rapid_color)
        self.internal_pref.configure(text=self.cut_color_internal, fg_color=self.cut_color_internal)
        self.external_pref.configure(text=self.cut_color_external, fg_color=self.cut_color_external)
        self.shape_pref.configure(text=self.shape_color, fg_color=self.shape_color)
        self.leadin_pref.configure(text=self.leadin_color, fg_color=self.leadin_color)
        self.selected_pref.configure(text=self.selected_color, fg_color=self.selected_color)
        self.invalid_pref.configure(text=self.invalid_color, fg_color=self.invalid_color)

    def load_preferences(self):
        if Path.is_file(self.prefs_file):
            with open(self.prefs_file, 'r') as f:
                for line in f:
                    parameter, data = line.split('=')
                    match(parameter.strip()):
                        case 'Units':
                            self.units = data.strip()
                        case 'Precision':
                            self.precision = int(data.strip())
                        case 'Lead-in Length':
                            self.lead_length = float(data.strip())
                        case  'Lead-in Angle':
                            self.lead_angle = int(data.strip())
                        case 'Lead-in Type':
                            self.lead_type = data.strip()
                        case 'Small Hole Diameter':
                            self.small_hole = float(data.strip())
                        case  'Arc Flattening Distance':
                            self.flattening_distance = float(data.strip())
                        case  'Gap Tolerance':
                            self.gap_tolerance = float(data.strip())
                        case 'Canvas Back':
                            self.canvas_color = data.strip()
                        case 'Rapid Move':
                            self.rapid_color = data.strip()
                        case 'Internal Cut':
                            self.cut_color_internal = data.strip()
                        case 'External Cut':
                            self.cut_color_external = data.strip()
                        case 'Original Shape':
                            self.shape_color = data.strip()
                        case 'Lead-in':
                            self.leadin_color = data.strip()
                        case 'Selected':
                            self.selected_color = data.strip()
                        case 'Invalid':
                            self.invalid_color = data.strip()
                        case 'Last Path':
                            self.current_path = data.strip()
                        case 'Geometry':
                            self.geometry(data.strip())
                        case 'Material File':
                            self.material_file = data.strip()
                        case _:
                            pass
        else:
            title='Units Selection'
            message='Should metric be saved as the default units?'
            metric = Msg.askyesno(self, title, message)
            match(metric):
                case 'Yes':
                    self.units = 'metric'
                    self.precision = 2
                    self.lead_length = 5.0
                    self.small_hole = 32.0
                    self.flattening_distance = 0.025
                    self.gap_tolerance = 0.001
                case _:
                    self.units = 'dinosaur'
                    self.precision = 2
                    self.lead_length = 0.2
                    self.small_hole = 1.25
                    self.gap_tolerance = 0.00004
            self.lead_angle = 45
            self.lead_type = 'line'
            self.canvas_color = '#bfbfbf'
            self.rapid_color = '#e5e5e5'
            self.cut_color_internal = '#00ffff'
            self.cut_color_external = '#ffa500'
            self.shape_color = '#404040'
            self.leadin_color = '#ffff00'
            self.selected_color = '#660000'
            self.invalid_color = '#ff0000'
            self.current_path = str(Path.home())
            self.save_preferences()

    def save_preferences(self):
        with open(self.prefs_file, 'w') as f:
            f.write(f'Units = {self.units}\n')
            f.write(f'Precision = {self.precision}\n')
            f.write(f'Lead-in Length = {self.lead_length}\n')
            f.write(f'Lead-in Angle = {self.lead_angle}\n')
            f.write(f'Lead-in Type = {self.lead_type}\n')
            f.write(f'Small Hole Diameter = {self.small_hole}\n')
            f.write(f'Arc Flattening Distance = {self.flattening_distance}\n')
            f.write(f'Gap Tolerance = {self.gap_tolerance}\n')
            f.write(f'Canvas Back = {self.canvas_color}\n')
            f.write(f'Rapid Move = {self.rapid_color}\n')
            f.write(f'Internal Cut = {self.cut_color_internal}\n')
            f.write(f'External Cut = {self.cut_color_external}\n')
            f.write(f'Original Shape = {self.shape_color}\n')
            f.write(f'Lead-in = {self.leadin_color}\n')
            f.write(f'Selected = {self.selected_color}\n')
            f.write(f'Invalid = {self.invalid_color}\n')
            f.write(f'Last Path = {self.current_path}\n')
            f.write(f'Geometry = {self.geometry()}\n')
            f.write(f'Material File = {self.material_file}\n')

if __name__ == '__main__':
    app = App()
    app.mainloop()
