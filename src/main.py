#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Phillip A Carter
# SPDX-License-Identifier: GPL-2.0-only

import math
import os
import sys
from pathlib import Path
from tkinter import Canvas
from tkinter import simpledialog as Sd
from tkinter.filedialog import askopenfilename as Open
from tkinter.filedialog import asksaveasfilename as Save

import ctkmessagebox2 as Msg
import customtkinter as CTk
from CTkColorPicker import AskColor as Color
from PIL import Image

from .dxf_to_plasmac import dxf2PlasmaC

VERSION = '0.1.0'

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
        self.D2P = dxf2PlasmaC()
        # color preferences
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
        # self.material_dict = {}
        self.material_file = ''
        # tkinter preferences
        self.units_var = CTk.StringVar()
        self.precision_var = CTk.StringVar()
        self.lead_type_var = CTk.StringVar()
        self.material_file_var = CTk.StringVar()
        self.material_var = CTk.StringVar()
        self.feed_r_var = CTk.StringVar()
        self.kerf_var = CTk.StringVar()
        self.cut_h_var = CTk.StringVar()
        self.pierce_h_var = CTk.StringVar()
        self.pierce_d_var = CTk.StringVar()
        self.load_preferences()
        # window set up
        CTk.set_default_color_theme('dark-blue') # blue, green, or dark-blue
        CTk.set_appearance_mode('dark') # light or dark
        self.minsize(760, 540)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.protocol('WM_DELETE_WINDOW', self.shutdown)
        self.title('dxf2PlasmaC')

        self.show_rapids = True
        self.rapid_arrow_len = 5
        self.canvas_size = (1, 1)
        self.canvas_last = {'scale': 1.0, 'x': 0.0, 'y': 0.0}
        self.canvas_first = {'x': 0.0, 'y': 0.0}
        self.new_file = False
        self.D2P.loaded_file = ''
        self.selected_item = ''
        self.mouse = (0, 0)
        self.gcode_file = ''
        self.mod_key = 'Command' if sys.platform == 'darwin' else 'Control'
        self.tt_delay = 0.6 # tooltip delay
        self.icon_path = get_asset_path('assets/icons')

        self.create_main_page()
        self.create_prefs_frame()
        self.create_main_frame()
        self.create_menu_bar()
        self.create_side_bar()
        # all widgets instantiated so apply preferences
        self.set_preferences()

    def do_plot(self):
        self.plot(self.D2P.shape_points, 'shape', True)
        self.plot(self.D2P.cut_points, 'cut', False)
        self.update()
        if self.canvas.winfo_ismapped():
            if self.new_file:
                self.zoom_all()
                self.new_file = False
            else:
                self.canvas.scale('all', 0, 0, self.canvas_last['scale'], self.canvas_last['scale'])
                self.canvas.move('all', self.canvas_last['x'], self.canvas_last['y'])

    def plot(self, points, mode:str='shape', clear:bool=False):
        ''' plot a job '''
        # the only difference between metric and inch are the origin pointer lengths
        spot = 0.5 if self.D2P.units == 'metric' else 0.02
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
        for layer in self.D2P.layers:
            if layer in self.D2P.ignored:
                continue
            for point in self.D2P.sequences[layer]['cut']:
                 # shape was too small to offset
                print('\n',points[layer][point])
                if not points[layer][point]:
                    seq += 1
                    continue
                # iterate through segments
                for segment in points[layer][point]:
                    line = points[layer][point][segment]
                    if 'start' not in line:
                        continue
                    state = 'disabled' if mode != 'cut' or segment == 0 else 'normal'
                    fill = (self.shape_color if mode == 'shape' else
                            self.rapid_color if segment == 0 else
                            self.leadin_color if segment == 1 else
                            self.cut_color_external if self.D2P.sequences[layer]['external'][point] else
                            self.invalid_color if not self.D2P.sequences[layer]['lead-in'][point]['valid'] else
                            self.cut_color_internal)
                    seg_type = 'rapid' if segment == 0 else 'lead-in' if segment == 1 else 'feed'
                    tags = (mode, str(seq), str(line['seg']), fill, seg_type, f'layer_{layer}')
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

    def create_layer_widgets(self):
        for widget in self.layer_frame.winfo_children():
            widget.destroy()
        for layer in self.D2P.layers:
            check = CTk.CTkCheckBox(self.layer_frame, text=layer)
            if layer not in self.D2P.ignored:
                check.select()
            check.configure(command=lambda c=check, l=f'layer_{layer}': self.toggle_layer(l, c))
            check.pack(padx=4, pady=(0, 4), expand=True, fill='x', anchor='w')

#FIXME - move som of this to D2P
    def show_option_popup(self, event):
        ''' display the context menu at the mouse cursor position '''
        if self.selected_item:
            tags = self.canvas.itemcget(self.selected_item, 'tags')
            seq = int(tags.split()[1])
            layer = tags.split()[5].split('_', 1)[1]
            cut = self.D2P.sequences[layer]['cut'][int(tags.split()[1])]
            path = self.D2P.paths[layer][self.D2P.sequences[layer]['cut'][seq]]
            segment = int(tags.split()[2])
            external_cut = self.D2P.sequences[layer]['external'][self.D2P.sequences[layer]['cut'][seq]]
            radius = path.get('r', None) if isinstance(path, dict) else None
            opts = ['', '']
            if segment == 0:
                return
            elif segment == 1:
                # add 1 so user doesn't see cut sequence #0
                title = f'Cut: #{seq + 1}   Lead-in'
                opt1 = 'Line \u2192 Arc' if self.D2P.sequences[layer]['lead-in'][cut]['type'] == 'line' else 'Arc \u2192 Line'
                if radius and radius < self.D2P.small_hole / 2 and not external_cut:
                    opts = ['Change Length']
                else:
                    opts = [opt1, 'Change Length']
                    if self.D2P.sequences[layer]['lead-in'][cut]['type'] == 'line':
                        opts.append('Change Angle')
                color = self.leadin_color
            else:
                # add 1 so user doesn't see cut sequence #0
                # title = f'Cut: #{seq + 1}   Segment: #{segment + 1}'
                title = f'Cut: #{seq + 1}   Segment: #{segment}'
                opt1 = 'External \u2192 Internal' if self.D2P.sequences[layer]['external'][cut] else 'Internal \u2192 External'
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
                    self.D2P.toggle_lead(layer, cut)
                    self.error_check()
                    self.do_plot()
                case 'Change Length':
                    self.color_selected(self.canvas.type(self.selected_item), False)
                    self.selected_item = ''
                    self.after(100, self.lead_in_length, cut, radius, external_cut, layer)
                case 'Change Angle':
                    self.color_selected(self.canvas.type(self.selected_item), False)
                    self.selected_item = ''
                    self.after(100, self.lead_in_angle, cut, layer)
                case 'Internal \u2192 External' | 'External \u2192 Internal':
                    self.selected_item = ''
                    self.D2P.toggle_side(layer, cut)
                    self.error_check()
                    self.do_plot()
                case 'Change Cut Sequence':
                    self.color_selected(self.canvas.type(self.selected_item), False)
                    self.selected_item = ''
                    self.after(100, self.change_sequence, cut, seq, layer)
                case 'Set As Start Segment':
                    self.selected_item = ''
                    self.D2P.change_start_segment(layer, cut, segment)
                    self.error_check()
                    self.do_plot()
                case 'Change Start Angle':
                    self.color_selected(self.canvas.type(self.selected_item), False)
                    self.selected_item = ''
                    self.after(100, self.change_start_angle, cut, seq, layer)
                case _:
                    pass
            if self.selected_item:
                self.color_selected(self.canvas.type(self.selected_item), False)
                self.selected_item = ''

    def change_sequence(self, cut, seq, layer):
        # add 1 here so user doesn't see cut sequence #0
        mini = min(self.D2P.sequences[layer]['cut']) + 1
        maxi = max(self.D2P.sequences[layer]['cut']) + 1
        new_seq = Sd.askinteger('Cut Sequence',
                             f'Select a new cut position\nfrom {mini} to {maxi}',
                             initialvalue=seq + 1,
                             minvalue=mini,
                             maxvalue=maxi,
                             parent=self)
        if new_seq is not None and new_seq != seq + 1:
            self.D2P.change_cut_sequence(layer, cut, new_seq)
            self.error_check()
            self.do_plot()

    def change_start_angle(self, cut, seq, layer):
        mini = 0
        maxi = 359
        ang = Sd.askinteger('Cut Start Angle',
                             f'Select a new start position\nfrom {mini} to {maxi}',
                             initialvalue=self.D2P.sequences[layer]['start'][cut],
                             minvalue=mini,
                             maxvalue=maxi,
                             parent=self)
        if ang is not None and ang != seq + 1:
            self.D2P.change_start_angle(layer, cut, ang)
            self.error_check()
            self.do_plot()

    def lead_in_length(self, cut, radius, external_cut, layer):
        maxi = radius if radius and radius < self.D2P.small_hole and not external_cut else 10
        length = Sd.askfloat('Lead-in Length',
                             f'Enter a new lead-in length\nfom 0 to {maxi}',
                             initialvalue=self.D2P.sequences[layer]['lead-in'][cut]['length'],
                             minvalue=0,
                             maxvalue=maxi,
                             parent=self)
        if length is not None:
            self.D2P.change_lead_in_length(layer, cut, length)
            self.error_check()
            self.do_plot()

    def lead_in_angle(self, cut, layer):
        angle = Sd.askinteger('Lead-in Angle',
                             'Enter lead-in angle:',
                             initialvalue=self.D2P.sequences[layer]['lead-in'][cut]['angle'],
                             minvalue=10,
                             maxvalue=90,
                             parent=self)
        if angle is not None:
            self.D2P.change_lead_in_angle(layer, cut, angle)
            self.error_check()
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
        # store the current scale and offsets
        if self.new_file:
            self.canvas_last['scale'] = scale
            self.canvas_last['x'] = xMove
            self.canvas_last['y'] = yMove
            self.canvas_first['x'] = xMove
            self.canvas_first['y'] = yMove
        else:
            self.canvas_last['scale'] *= scale
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

    def error_check(self):
        if self.D2P.warning:
           Msg.showwarning(self, 'Warning', '\n'.join(self.D2P.warning))
        if self.D2P.error:
            Msg.showerror(self, 'Error', self.D2P.error)
            return True
        return False

    def reload(self, _event):
        self.D2P.reload_file()
        if self.error_check():
            return
        self.create_layer_widgets() # need this in case some layers were disabled
        self.do_plot()

    def open_project(self, _event):
        file = Open(parent=self,
                    title='Open Project',
                    filetypes=[('Project File', '*.d2p'), ('Any File', '*.*')],
                    initialdir=self.current_path,
                    initialfile = Path(self.D2P.loaded_file).stem)
        if file:
            self.current_path = str(Path(file).parent)
            self.title(f'dxf2PlasmaC     project file: {Path(file).name}')
            self.new_file = True
            self.selected_item = ''
            self.D2P.open_project(file)
            if self.error_check():
                return
            self.create_layer_widgets()
            self.do_plot()

    def save_project(self, _event):
        file = Save(parent=self,
                    title='Save Project',
                    filetypes=[('Project File', '*.d2p'), ('Any File', '*.*')],
                    initialdir=self.current_path,
                    initialfile = Path(self.D2P.loaded_file).stem)
        if file:
            self.current_path = str(Path(file).parent)
            self.D2P.save_project(file)
            self.error_check()

    def import_dxf(self, _event):
        file = Open(parent=self,
                    title='Open DXF File',
                    filetypes=[('DXF File', '.dxf'), ('Any File', '*.*')],
                    initialdir=self.current_path)
        if file:
            self.title(f'dxf2PlasmaC     dxf file: {Path(file).name}')
            self.current_path = str(Path(file).parent)
            self.new_file = True
            self.D2P.open_dxf(file)
            if self.error_check():
                return
            self.create_layer_widgets()
            post = 'mm' if self.D2P.units == 'metric' else 'in'
            self.title(f'{self.title()}     Size: {self.D2P.size[0]}{post} x {self.D2P.size[1]}{post}')
            self.do_plot()


    def get_points(self, mode: str):
        self.D2P.get_points(mode)
        self.error_check()

    def export_gcode(self, _event):
        file = Save(parent=self,
                    title='Save GCode File',
                    filetypes=[('GCode File', '*.ngc'), ('Any File', '*.*')],
                    initialdir=self.current_path,
                    initialfile = Path(self.D2P.loaded_file).stem)
        if file:
            self.D2P.write_gcode(file)
            self.error_check()

    def show_preferences_frame(self, _event):
        self.prefs_frame.lift()

    def show_materials_frame(self, _event):
        self.materials_frame.lift()

    def show_about(self, _event):
        title = 'About dxf2plasmac'
        message = (f'Version {VERSION}'
                   '\n'
                   '\nA basic converter from dxf to QtPlasmaC G-code'
                   '\n'
                   '\nPortions of this software utilize the following:'
                   '\nLucide Icons <https://lucide.dev>'
                   '\nezdxf library. <https://github.com/mozman/ezdxf>'
                   '\nshapely library <https://github.com/shapely/shapely>'
                   '\npillow library <https://github.com/python-pillow/Pillow>'
                   '\n'
                   '\nLicensing for these is can be found in ATTRIBUTIONS.md'
                  )
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
        # material selector
        mat = CTk.CTkFrame(self.main_frame)
        mat.grid(row=2, column=0, columnspan=2, sticky='w')
        mat.grid_columnconfigure(1, weight=1)
        label_material = CTk.CTkLabel(mat, text='Material:', width=80, anchor='e')
        label_material.grid(row=0, column=0, padx=4, pady=(4, 0), sticky='ew')
        self.material_select = CTk.CTkOptionMenu(mat, width=240, variable=self.material_var, values=['None'], command=self.select_material, anchor='w')
        self.material_select.grid(row=0, column=1, padx=4, pady=0, sticky='nsew')

    def create_menu_bar(self):
        menu = CTk.CTkFrame(self.main_frame)
        menu.grid(row=0, column=0, columnspan=2, sticky='ew')
        size = 36
        col = 0
        im = CTk.CTkImage(Image.open(f'{self.icon_path}/import_dxf.png'), size=(size, size))
        iml = CTk.CTkLabel(master = menu, image=im, width=size, height=size, bg_color='gray60', text='')
        iml.image = im
        iml.bind('<Button-1>', self.import_dxf)
        iml.grid(row=0, column=col, padx=(2, 0), pady=(2, 0))
        col += 1
        ex = CTk.CTkImage(Image.open(f'{self.icon_path}/export_gcode.png'), size=(size, size))
        exl = CTk.CTkLabel(master = menu, image=ex, width=size, height=size, bg_color='gray60', text='')
        exl.image = ex
        exl.bind('<Button-1>', self.export_gcode)
        exl.grid(row=0, column=col, padx=(4, 0), pady=(2, 0))
        col += 1
        rl = CTk.CTkImage(Image.open(f'{self.icon_path}/reload.png'), size=(size, size))
        rll = CTk.CTkLabel(master = menu, image=rl, width=size, height=size, bg_color='gray60', text='')
        rll.image = rl
        rll.bind('<Button-1>', self.reload)
        rll.grid(row=0, column=col, padx=(24, 0), pady=(2, 0))
        col += 1
        op = CTk.CTkImage(Image.open(f'{self.icon_path}/open_project.png'), size=(size, size))
        opl = CTk.CTkLabel(master = menu, image=op, width=size, height=size, bg_color='gray60', text='')
        opl.image = op
        opl.bind('<Button-1>', self.open_project)
        opl.grid(row=0, column=col, padx=(24, 0), pady=(4, 2))
        col += 1
        sp = CTk.CTkImage(Image.open(f'{self.icon_path}/save_project.png'), size=(size, size))
        spl = CTk.CTkLabel(master = menu, image=sp, width=size, height=size, bg_color='gray60', text='')
        spl.image = sp
        spl.bind('<Button-1>', self.save_project)
        spl.grid(row=0, column=col, padx=(4, 0), pady=(2, 0))
        col += 1
        si = CTk.CTkImage(Image.open(f'{self.icon_path}/settings.png'), size=(size, size))
        sl = CTk.CTkLabel(master = menu, image=si, width=size, height=size, bg_color='gray60', text='')
        sl.image = si
        sl.bind('<Button-1>', self.show_preferences_frame)
        sl.grid(row=0, column=col, padx=(24, 0), pady=(2, 0))
        col += 1
        a = CTk.CTkImage(Image.open(f'{self.icon_path}/info.png'), size=(size, size))
        al = CTk.CTkLabel(master = menu, image=a, width=size, height=size, bg_color='gray60', text='')
        al.image = a
        al.bind('<Button-1>', self.show_about)
        al.grid(row=0, column=col, padx=(24, 0), pady=(2, 0))
        col += 1
        za = CTk.CTkImage(Image.open(f'{self.icon_path}/zoom_all.png'), size=(size, size))
        zal = CTk.CTkLabel(master = menu, image=za, width=size, height=size, bg_color='gray60', text='')
        zal.image = za
        zal.bind('<Button-1>', self.zoom_all)
        zal.grid(row=0, column=col, padx=(100, 0), pady=(2, 0))
        col += 1
        zi = CTk.CTkImage(Image.open(f'{self.icon_path}/zoom_in.png'), size=(size, size))
        zil = CTk.CTkLabel(master = menu, image=zi, width=size, height=size, bg_color='gray60', text='')
        zil.image = zi
        zil.bind('<Button-1>', self.zoom_in)
        zil.grid(row=0, column=col, padx=(24, 0), pady=(2, 0))
        col += 1
        zo = CTk.CTkImage(Image.open(f'{self.icon_path}/zoom_out.png'), size=(size, size))
        zol = CTk.CTkLabel(master = menu, image=zo, width=size, height=size, bg_color='gray60', text='')
        zol.image = zo
        zol.bind('<Button-1>', self.zoom_out)
        zol.grid(row=0, column=col, padx=(4, 0), pady=(2, 0))
        col += 1
        pl = CTk.CTkImage(Image.open(f'{self.icon_path}/pan_left.png'), size=(size, size))
        pll = CTk.CTkLabel(master = menu, image=pl, width=size, height=size, bg_color='gray60', text='')
        pll.image = pl
        pll.bind('<Button-1>', self.pan_left)
        pll.grid(row=0, column=col, padx=(24, 0), pady=(2, 0))
        col += 1
        pr = CTk.CTkImage(Image.open(f'{self.icon_path}/pan_right.png'), size=(size, size))
        prl = CTk.CTkLabel(master = menu, image=pr, width=size, height=size, bg_color='gray60', text='')
        prl.image = pr
        prl.bind('<Button-1>', self.pan_right)
        prl.grid(row=0, column=col, padx=(4, 0), pady=(2, 0))
        col += 1
        pu = CTk.CTkImage(Image.open(f'{self.icon_path}/pan_up.png'), size=(size, size))
        pul = CTk.CTkLabel(master = menu, image=pu, width=size, height=size, bg_color='gray60', text='')
        pul.image = pu
        pul.bind('<Button-1>', self.pan_up)
        pul.grid(row=0, column=col, padx=(4, 0), pady=(2, 0))
        col += 1
        pd = CTk.CTkImage(Image.open(f'{self.icon_path}/pan_down.png'), size=(size, size))
        pdl = CTk.CTkLabel(master = menu, image=pd, width=size, height=size, bg_color='gray60', text='')
        pdl.image = pd
        pdl.bind('<Button-1>', self.pan_down)
        pdl.grid(row=0, column=col, padx=(4, 2), pady=(2, 0))

    def create_side_bar(self):
        side = CTk.CTkFrame(self.main_frame)
        side.grid(row=1, column=0, sticky='ns')
        side.grid_rowconfigure((2, 4), weight=1)
        layers = CTk.CTkLabel(side, text='Layers')#, anchor='w')
        layers.grid(row=0, column=0, columnspan=2, padx=(4, 2), pady=(4, 2), sticky='new')
        self.layer_frame = CTk.CTkFrame(side, width=100, fg_color='transparent')
        self.layer_frame.grid(row=1, column=0, columnspan=2, sticky='new')
        check = CTk.CTkCheckBox(side, text='Rapids')
        check.select()
        check.configure(command=self.toggle_rapids)
        check.grid(row=3, column=0, columnspan=2, padx=(4, 2), pady=(4, 2), sticky='new')
        ew = 48 # entry width
        row = 5
        kerf = CTk.CTkLabel(side, text='Kerf Width:', anchor='e')
        kerf.grid(row=row, column=0, padx=(4, 2), pady=(4, 2), sticky='nsew')
        kerf_entry = CTk.CTkEntry(side, textvariable=self.kerf_var, width=ew, border_width=1)
        kerf_entry.bind('<Return>', lambda e:self.kerf_changed(kerf_entry.get()))
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
            if self.D2P.units == 'metric':
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

    def apply_prefs(self):
        self.get_preferences()
        self.canvas.config(bg=self.canvas_color)
        for layer in self.D2P.layers:
            for path in self.D2P.sequences[layer]['lead-in']:
                self.D2P.sequences[layer]['lead-in'][path]['length'] = self.D2P.lead_length
                self.D2P.sequences[layer]['lead-in'][path]['angle'] = self.D2P.lead_angle
                self.D2P.sequences[layer]['lead-in'][path]['type'] = self.D2P.lead_type
        if self.D2P.loaded_file:
            self.get_points('cut')
            self.do_plot()

    def close_prefs(self):
        ''' close preferences window '''
        self.prefs_frame.lower()

    def toggle_layer(self, layer, widget):
        ''' toggle vivibility of layer '''
        if widget.get():
            self.D2P.ignored.remove(layer)
            state = 'normal'
        else:
            self.D2P.ignored.append(layer)
            state = 'hidden'
        self.canvas.itemconfig(layer, state=state)

    def toggle_rapids(self):
        ''' toggle visibility of rapid moves '''
        state = 'hidden' if self.show_rapids else 'normal'
        self.canvas.itemconfig('rapid', state=state)
        self.show_rapids = not self.show_rapids

    def set_color(self, widget, title='title'):
        ''' select a new color '''
        color = Color(title=f'Choose A {title} Color', initial_color=widget.cget('fg_color')).get()
        if color:
            widget.configure(text=color, fg_color=color)
        self.update_idletasks()
        self.focus_force()

    def load_material_file(self):
        ''' load materials form material file '''
        self.material_file_var.set(Path(self.material_file).name)
        self.D2P.load_materials(self.material_file)
        if self.error_check():
            return
        self.material_select.configure(values=self.D2P.material_names)
        self.show_material()
        self.do_plot()

    def select_material(self, material):
        ''' selected a material '''
        self.D2P.select_material(material.split(':')[0].strip())
        self.show_material()
        self.do_plot()

    def show_material(self):
        ''' display material values in the sidebar'''
        self.material_var.set(f'{self.D2P.material['nu']}:  {self.D2P.material['na']}')
        self.pierce_h_var.set(self.D2P.material['ph'])
        self.pierce_d_var.set(self.D2P.material['pd'])
        self.cut_h_var.set(self.D2P.material['ch'])
        self.feed_r_var.set(self.D2P.material['fr'])
        self.kerf_var.set(self.D2P.material['kw'])

    def kerf_changed(self, value):
        ''' kerf width changed so redraw '''
        try:
            self.D2P.kerf = float(value)
            self.get_points('cut')
            self.do_plot()
        except ValueError:
            pass

    def get_preferences(self):
        ''' applies preference page widget values to the preference variables '''
        self.D2P.units = self.units_var.get()
        self.D2P.precision = int(self.precision_var.get())
        self.D2P.lead_length = float(self.lead_length_pref.get())
        self.D2P.lead_angle = int(self.lead_angle_pref.get())
        self.D2P.lead_type = self.lead_type_var.get()
        self.D2P.small_hole = float(self.small_hole_pref.get())
        self.D2P.flattening_distance = float(self.flattening_pref.get())
        self.D2P.gap_tolerance = float(self.gap_pref.get())
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
        self.units_var.set(self.D2P.units)
        self.precision_var.set(self.D2P.precision)
        self.lead_length_pref.delete(0, CTk.END)
        self.lead_length_pref.insert(0, self.D2P.lead_length)
        self.lead_angle_pref.delete(0, CTk.END)
        self.lead_angle_pref.insert(0, self.D2P.lead_angle)
        self.lead_type_var.set(self.D2P.lead_type)
        self.small_hole_pref.delete(0, CTk.END)
        self.small_hole_pref.insert(0, self.D2P.small_hole)
        self.flattening_pref.delete(0, CTk.END)
        self.flattening_pref.insert(0, self.D2P.flattening_distance)
        self.gap_pref.delete(0, CTk.END)
        self.gap_pref.insert(0, self.D2P.gap_tolerance)
        self.canvas_bg_pref.configure(text=self.canvas_color, fg_color=self.canvas_color)
        self.rapid_pref.configure(text=self.rapid_color, fg_color=self.rapid_color)
        self.internal_pref.configure(text=self.cut_color_internal, fg_color=self.cut_color_internal)
        self.external_pref.configure(text=self.cut_color_external, fg_color=self.cut_color_external)
        self.shape_pref.configure(text=self.shape_color, fg_color=self.shape_color)
        self.leadin_pref.configure(text=self.leadin_color, fg_color=self.leadin_color)
        self.selected_pref.configure(text=self.selected_color, fg_color=self.selected_color)
        self.invalid_pref.configure(text=self.invalid_color, fg_color=self.invalid_color)

    def load_preferences(self):
        ''' load variables with appropriate values from preferences file '''
        if Path.is_file(self.prefs_file):
            with open(self.prefs_file, 'r') as f:
                for line in f:
                    parameter, data = line.split('=')
                    match(parameter.strip()):
                        case 'Units':
                            self.D2P.units = data.strip()
                        case 'Precision':
                            self.D2P.precision = int(data.strip())
                        case 'Lead-in Length':
                            self.D2P.lead_length = float(data.strip())
                        case  'Lead-in Angle':
                            self.D2P.lead_angle = int(data.strip())
                        case 'Lead-in Type':
                            self.D2P.lead_type = data.strip()
                        case 'Small Hole Diameter':
                            self.D2P.small_hole = float(data.strip())
                        case  'Arc Flattening Distance':
                            self.D2P.flattening_distance = float(data.strip())
                        case  'Gap Tolerance':
                            self.D2P.gap_tolerance = float(data.strip())
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
                    self.D2P.units = 'metric'
                    self.D2P.precision = 2
                    self.D2P.lead_length = 5.0
                    self.D2P.small_hole = 32.0
                    self.D2P.flattening_distance = 0.025
                    self.D2P.gap_tolerance = 0.001
                case _:
                    self.D2P.units = 'dinosaur'
                    self.D2P.precision = 2
                    self.D2P.lead_length = 0.2
                    self.D2P.small_hole = 1.25
                    self.D2P.gap_tolerance = 0.00004
            self.D2P.lead_angle = 45
            self.D2P.lead_type = 'line'
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
        ''' save variables values to preferences file '''
        with open(self.prefs_file, 'w') as f:
            f.write(f'Units = {self.D2P.units}\n')
            f.write(f'Precision = {self.D2P.precision}\n')
            f.write(f'Lead-in Length = {self.D2P.lead_length}\n')
            f.write(f'Lead-in Angle = {self.D2P.lead_angle}\n')
            f.write(f'Lead-in Type = {self.D2P.lead_type}\n')
            f.write(f'Small Hole Diameter = {self.D2P.small_hole}\n')
            f.write(f'Arc Flattening Distance = {self.D2P.flattening_distance}\n')
            f.write(f'Gap Tolerance = {self.D2P.gap_tolerance}\n')
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
