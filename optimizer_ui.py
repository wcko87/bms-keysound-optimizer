import tkinter as tk
import tkinter.scrolledtext
from tkinter import ttk
from tkinter import filedialog
from tkinter import messagebox
import optimizer_data
import optimizer_io
from utils import *
import itertools
import numpy as np
import math

import sounddevice as sd

FONT_HEADER = ("Arial", 10, 'bold')
FONT_MAIN = ("Arial", 10)
FONT_SMALL = ("Arial", 8)
APP_WIDTH = 1200
APP_HEIGHT = 700
SIDE_PANEL_WIDTH = 180

def configure_styles():
    style = ttk.Style()
    style.theme_use("clam")
    style.configure(
        "Large.TSpinbox",
        arrowsize=15,
        padding=3,
    )

def mouse_in_frame(frame):
    ## checks if the mouse is hovering over the canvas or any of its descendants
    try:
        x, y = frame.winfo_pointerxy()
        current = frame.winfo_containing(x, y)
    except Exception:
        current = None

    while current is not None:
        if current == frame:
            return True
        current = current.master # move to parent widget
    return False

def create_spinbox(parent, label, initial_value=0.0, min_value=0.0, max_value=float('inf'), increment=0.1, width=7, integer=False):
    container_frame = tk.Frame(parent)
    container_frame.pack()

    tk.Label(container_frame, text="%s:"%label, font=FONT_MAIN).pack(side="left")

    spinbox_kwargs = {
        "font": FONT_MAIN,
        "style": "Large.TSpinbox",
        "width": width,
    }

    if integer:
        variable = tk.IntVar(value=int(initial_value))
        spinbox_kwargs.update({
            "textvariable": variable,
            "from_": float(round(min_value)),
            "to": 10000.0 if max_value == float('inf') else float(round(max_value)),
            "increment": float(max(1, round(increment))),
        })
        display_format = '%d'  # Formats as a whole number
    else:
        variable = tk.DoubleVar(value=initial_value)
        display_format = '%0.2f'
        spinbox_kwargs.update({
            'textvariable': variable,
            'from_': min_value,
            'to': max_value,
            'increment': increment,
            'format': display_format,
        })

    spinbox = ttk.Spinbox(container_frame, **spinbox_kwargs)
    spinbox.bind("<MouseWheel>", lambda event: 'break')
    spinbox.pack(side="right")

    if not integer:
        # so that the initial value also displays with 2 d.p. because for some reason it doesn't if you don't do this
        spinbox.delete(0, "end")
        spinbox.insert(0, display_format%initial_value)

    return variable, spinbox, container_frame

class ScrollableFrame(tk.Frame):
    def __init__(self, parent, main_controller, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.main_controller = main_controller
        
        self.scrollbar = tk.Scrollbar(self, orient="vertical")
        self.scrollbar.pack(side="right", fill='y')

        self.canvas = tk.Canvas(self, borderwidth=0, background="#ffffff")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.scrollable_content = tk.Canvas(self.canvas, background="#ffffff")
        canvas_window_id = self.canvas.create_window((0, 0), window=self.scrollable_content, anchor="nw")
        #self.scrollable_content.pack(fill='x')

        self.scrollable_content.bind("<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self.canvas.bind("<Configure>",
            lambda e: self.canvas.itemconfig(canvas_window_id, width=e.width)
        )

        self.canvas.configure(yscrollcommand=self._on_scroll)
        self.scrollbar.config(command=self.canvas.yview)

        # used to override default mousewheel behavior so you don't get duplicate scrolling
        self.scrollbar.bind("<MouseWheel>", self.main_controller.on_mousewheel_y)

    def _on_scroll(self, *args):
        self.scrollbar.set(*args)
        self.main_controller.refresh_selection()

    def try_vertical_scroll(self, event):
        if mouse_in_frame(self):
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return 'break'

class KeysoundDrawer(object):
    def __init__(self, keysounds_canvas, opt_data, guid, draw_downsample=2):
        self.keysounds_canvas = keysounds_canvas
        self.opt_data = opt_data
        self.guid = guid
        self.clear_cache()
        self.draw_downsample = draw_downsample

    def clear_cache(self):
        self.last_rect_draw_state = None
        self.last_waveform_draw_state = None
        self.cached_coords_is_substitute = None
        self.cached_coords = None
        self.prev_drawn_id_pair = None
        self.rect = None
        self.label_text = None
        self.lines = {}

    def change_downsample(self, draw_downsample):
        self.draw_downsample = draw_downsample
        self.clear_cache()

    def is_in_viewport(self, viewport, bbox):
        return bbox[2] >= viewport[0] and bbox[0] <= viewport[1]

    def draw_keysound(self, viewport, bbox, in_view_y, keysound, substitute=False):
        self.draw_rect(bbox, keysound)
        self.draw_waveform(viewport, bbox, in_view_y, keysound, substitute)
        self.draw_label(viewport, bbox, in_view_y, keysound)

    def draw_label(self, viewport, bbox, in_view_y, keysound):
        in_viewport = self.is_in_viewport(viewport, bbox) and in_view_y
        if not in_viewport: return
        base_id = keysound.get_audio_data(substitute=False).id
        sub_id = keysound.get_audio_data(substitute=True).id
        if self.prev_drawn_id_pair == (base_id, sub_id): return
        self.prev_drawn_id_pair = (base_id, sub_id)

        if base_id == sub_id:
            text = f"{base_id}"
        else:
            text = f"{base_id} -> {sub_id}"

        x1, y1, x2, y2 = bbox
        if self.label_text is None:
            self.label_text = self.keysounds_canvas.create_text(0, 0, text=text, fill="black", font=("Verdana", 8))
        self.keysounds_canvas.coords(self.label_text, (x1+x2)/2, y1-8)
        self.keysounds_canvas.itemconfig(self.label_text, text=text)


    def draw_rect(self, bbox, keysound):
        selected = self.opt_data.is_keysound_selected(self.guid)
        substituted = keysound.has_substitution()
        if self.last_rect_draw_state == (selected, substituted): return
        self.last_rect_draw_state = (selected, substituted)

        x1, y1, x2, y2 = bbox
        #fill_color =  RowKeysoundManager.KEYSOUND_FILL_SELECTED if selected else RowKeysoundManager.KEYSOUND_FILL_UNSELECTED
        #outline_color = RowKeysoundManager.KEYSOUND_LINE_SELECTED if selected else RowKeysoundManager.KEYSOUND_LINE_UNSELECTED
        fill_color =  RowKeysoundManager.KEYSOUND_FILL_UNSELECTED
        outline_color = RowKeysoundManager.KEYSOUND_LINE_UNSELECTED
        if substituted:
            fill_color = blend_hex_colors(fill_color, '#b0ffe0', 0.5)
            #outline_color = blend_hex_colors(outline_color, '#0000ff', 0.8)
        if selected:
            #fill_color = blend_hex_colors(fill_color, '#ffffff', 0.8)
            outline_color = blend_hex_colors(outline_color, '#ff0000', 0.8)
        rect_thickness = 2

        if self.rect is None:
            self.rect = self.keysounds_canvas.create_rectangle(x1, y1, x2, y2, width=rect_thickness, outline=outline_color, fill=fill_color)
        self.keysounds_canvas.itemconfig(self.rect, width=rect_thickness, outline=outline_color, fill=fill_color)
        self.keysounds_canvas.coords(self.rect, x1, y1, x2, y2)

    def load_coords(self, bbox, keysound, substitute):
        if self.cached_coords is not None:
            if substitute == self.cached_coords_is_substitute:
                return
            # re-generate
            self.cached_coords_is_substitute = substitute

        x1, y1, x2, y2 = bbox
        data_stacked = None
        try:
            # Draw waveform line
            audio_data = keysound.get_audio_data(substitute=substitute)
            if audio_data is None: return
            data, sample_rate = audio_data.get_data()
            if data is None: return

            # when loaded as float64s using soundfile, data's default range is between -1.0 and 1.0
            # data is dtype float64, and has shape (num_samples, num_channels)
            skip = max(1, math.floor(data.shape[0]/(x2-x1))) * self.draw_downsample
            data_stacked = (data[::skip,:].copy() + 1)/2 * (y2 - y1) + y1
            x_axis = np.arange(0, data_stacked.shape[0])/data_stacked.shape[0]*(x2-x1) + x1
        finally:
            self.cached_coords = []
            if data_stacked is not None:
                for channel in range(data.shape[1]):
                    self.cached_coords.append((channel, np.vstack((x_axis, data_stacked[:,channel])).T.flatten()))

    def draw_waveform(self, viewport, bbox, in_view_y, keysound, substitute):
        in_viewport = self.is_in_viewport(viewport, bbox) and in_view_y
        if self.last_waveform_draw_state == (in_viewport, substitute): return
        self.last_waveform_draw_state = (in_viewport, substitute)

        if in_viewport:
            self.load_coords(bbox, keysound, substitute)

            for channel, coords in self.cached_coords:
                graph_line = self.lines.get(channel)
                if graph_line is None:
                    graph_line = self.keysounds_canvas.create_line([0, 0, 0, 0], fill=RowKeysoundManager.KEYSOUND_WAVE_LINE, width=2)
                    self.lines[channel] = graph_line
                self.keysounds_canvas.coords(graph_line, *coords)
        else:
            for graph_line in self.lines.values():
                self.keysounds_canvas.coords(graph_line, bbox)

class RowKeysoundManager(object):
    KEYSOUND_DEFAULT_DURATION_MS = 200
    KEYSOUND_FILL_UNSELECTED = "#e0e0e0"
    KEYSOUND_LINE_UNSELECTED = "#909090"
    #KEYSOUND_FILL_SELECTED = "#e0e0e0"
    #KEYSOUND_LINE_SELECTED = "#ff3020"
    KEYSOUND_WAVE_LINE = "#801010"

    def __init__(self, main_controller, keysounds_canvas, row_widget, panel_width, base_panel_height, keysounds):
        self.max_scroll_width = 12000
        self.main_controller = main_controller
        self.row_widget = row_widget
        self.opt_data = main_controller.opt_data
        self.keysounds_canvas = keysounds_canvas
        self.panel_width = panel_width
        self.base_panel_height = base_panel_height
        self.panel_height = base_panel_height

        self.keysounds_canvas.config(scrollregion=(0, 0, self.max_scroll_width, 0))
        self.keysound_drawers = {}

        self.generate_bounding_boxes(keysounds)
        self.redraw()

    def keysound_duration_ms(self, keysound, substitute=False):
        duration = keysound.get_audio_data(substitute).get_duration_ms()
        if duration is not None: return duration
        return RowKeysoundManager.KEYSOUND_DEFAULT_DURATION_MS

    def generate_bounding_boxes(self, keysounds):
        self.keysound_hitboxes = []

        keysound_starts = [keysound.get_ms_from_start() for keysound in keysounds]
        keysound_durations = [self.keysound_duration_ms(keysound) for keysound in keysounds]
        end_position_ms = max(start+duration for start, duration in zip(keysound_starts, keysound_durations))
        
        MS_PADDING = 200
        canvas_left_ms = -MS_PADDING
        canvas_right_ms = end_position_ms + MS_PADDING

        unended = {}
        rows_needed = 1
        for keysound, start_ms, duration_ms in zip(keysounds, keysound_starts, keysound_durations):
            unended = {i:t for i, t in unended.items() if t > start_ms}
            end_ms = start_ms + duration_ms
            row = min((i for i in range(1, len(unended) + 2) if i not in unended), default=1)
            unended[row] = end_ms
            rows_needed = max(row, rows_needed)
            base_y = self.base_panel_height * (row - 1)

            x1 = (start_ms - canvas_left_ms)/(canvas_right_ms - canvas_left_ms) * self.max_scroll_width
            x2 = (end_ms - canvas_left_ms)/(canvas_right_ms - canvas_left_ms) * self.max_scroll_width
            y1 = base_y + 15
            y2 = base_y + self.panel_height - 5
            self.keysound_hitboxes.append(((x1, y1, x2, y2), keysound))

        self.keysounds_canvas.config(height=self.base_panel_height*rows_needed)

    def get_viewport_x(self):
        buffer = 50
        x_scroll = self.keysounds_canvas.xview()
        view_x1 = x_scroll[0] * self.max_scroll_width - buffer
        view_x2 = x_scroll[1] * self.max_scroll_width + buffer
        return view_x1, view_x2

    def is_in_view_y(self):
        view_y1, view_y2 = self.main_controller.get_scroll_frame_viewport()
        row_y1 = self.row_widget.winfo_y()
        row_y2 = row_y1 + self.row_widget.winfo_height()    
        return row_y2 >= view_y1 and row_y1 <= view_y2

    def clear_drawings(self):
        self.keysounds_canvas.delete("all")
        for drawer in self.keysound_drawers.values():
            drawer.clear()
        self.keysound_drawers = {}

    def redraw(self):
        viewport = self.get_viewport_x()
        in_view_y = self.is_in_view_y()
        if self.keysound_hitboxes is None: return
        for bbox, keysound in self.keysound_hitboxes:
            if keysound.guid not in self.keysound_drawers:
                self.keysound_drawers[keysound.guid] = KeysoundDrawer(self.keysounds_canvas, self.opt_data, keysound.guid)
            self.keysound_drawers[keysound.guid].draw_keysound(viewport, bbox, in_view_y, keysound, self.main_controller.draw_substitute_keysounds)

    def is_within(self, hitbox, x, y):
        x1, y1, x2, y2 = hitbox
        return x >= x1 and y >= y1 and x <= x2 and y <= y2

    def on_canvas_click(self, event):
        if self.keysound_hitboxes is None: return
        click_x = event.widget.canvasx(event.x)
        click_y = event.y
        #print(f'{click_x}, {click_y}')
        # linear search, hopefully there aren't enough hitboxes for this to take a significant amount of time.
        keysound = next((keysound for hitbox, keysound in self.keysound_hitboxes if self.is_within(hitbox, click_x, click_y)), None)
        if keysound is None: return
        holding_shift = bool(event.state & 0x0001)  # Bit 0 represents Shift
        holding_ctrl = bool(event.state & 0x0004)   # Bit 2 represents Control
        self.main_controller.keysound_selection_click(keysound.guid, holding_shift, holding_ctrl)

class RowWidget(tk.Frame):
    BG_NORMAL = "#f1f3f5"
    #BG_SELECTED = "#a1c3f5"
    BG_SELECTED = "#ef729c"
    BG_SUBSTITUTED_HUE = '#c8fbe8'

    def __init__(self, main_controller, parent, opt_data, track):
        super().__init__(parent, pady=0, padx=5, bd=1, relief="solid")
        self.main_controller = main_controller
        self.opt_data = opt_data
        self.guid = track.guid
        self.track_name = track.track_name

        # Build UI
        self.keysounds_frame = self.configure_keysounds_panel(track.keysounds)
        self.keysounds_frame.pack(side="bottom", fill='x', padx=5)

        self.info_frame = tk.Frame(self, pady=0, padx=5, bd=1, relief="solid")
        self.info_frame.pack(side="left", padx=5)

        self.controls_frame = tk.Frame(self, pady=0, padx=5, bd=1, relief="solid")
        self.controls_frame.pack(side="right", padx=5)

        self.info_label = tk.Label(self.info_frame, text=self.track_name, font=FONT_MAIN)
        self.info_label.pack(side="top")
        #tk.Label(self.info_frame, text="<NAME>", font=FONT_MAIN).pack(side="bottom")

        #self.var_threshold, self.spinbox_threshold, self.container_threshold = create_spinbox(self.controls_frame, 'Threshold', width=7)
        #self.container_threshold.pack(side="right", pady=0, padx=(0,10))

        #self.var_volweight, self.spinbox_volweight, self.container_volweight = create_spinbox(self.controls_frame, 'Vol.Weight', initial_value=10, increment=1.0, width=7)
        #self.container_volweight.pack(side="right", pady=0, padx=(0,10))

        self.bind("<Button-1>", self.selection_click)
        self.keysounds_frame.bind("<Button-1>", self.selection_click)
        self.info_frame.bind("<Button-1>", self.selection_click)
        self.info_label.bind("<Button-1>", self.selection_click)
        self.controls_frame.bind("<Button-1>", self.selection_click)

    def selection_click(self, event):
        holding_shift = bool(event.state & 0x0001)  # Bit 0 represents Shift
        holding_ctrl = bool(event.state & 0x0004)   # Bit 2 represents Control
        self.main_controller.track_selection_click(self.guid, holding_shift, holding_ctrl)

    def refresh_selection_appearance(self):
        #bg_color = RowWidget.BG_SELECTED if self.opt_data.is_track_selected(self.guid) else RowWidget.BG_NORMAL
        bg_color = RowWidget.BG_NORMAL
        if any(ks.has_substitution() for ks in self.opt_data.get_keysounds_of_track(self.guid)):
            bg_color = blend_hex_colors(bg_color, RowWidget.BG_SUBSTITUTED_HUE, 0.9)
        if self.opt_data.is_track_selected(self.guid):
            bg_color = blend_hex_colors(bg_color, RowWidget.BG_SELECTED, 0.25)
        self.config(bg=bg_color)
        self.canvas_manager.redraw()

    def configure_keysounds_panel(self, keysounds):
        self.keysounds_frame = tk.Frame(self, pady=0, padx=1, bd=1, relief="solid")

        base_panel_height = 50
        panel_width = 700
        max_scroll_width = 1600

        self.h_scrollbar = tk.Scrollbar(self.keysounds_frame, orient='horizontal')
        self.h_scrollbar.pack(side='bottom', fill='x')

        self.keysounds_canvas = tk.Canvas(self.keysounds_frame,
            #xscrollcommand=self.h_scrollbar.set,
            xscrollcommand=self._on_scroll,
            width = panel_width,
            height = base_panel_height,
            borderwidth = 0,
            background = "#ffffff"
        )
        self.keysounds_canvas.pack(fill='x')

        self.canvas_manager = RowKeysoundManager(
            self.main_controller, self.keysounds_canvas, self, panel_width, base_panel_height, keysounds
        )
        self.keysounds_canvas.bind("<Button-1>", self.canvas_manager.on_canvas_click)

        self.h_scrollbar.config(command=self.keysounds_canvas.xview)
        self.h_scrollbar.bind("<Shift-MouseWheel>", self.main_controller.on_mousewheel_x)

        return self.keysounds_frame

    def try_horizontal_scroll(self, event):
        if mouse_in_frame(self):
            self.keysounds_canvas.xview_scroll(int(1 * (event.delta / 120)), "units")
        return 'break'

    def _on_scroll(self, *args):
        self.h_scrollbar.set(*args)
        x_view_pos = self.keysounds_canvas.xview()[0]
        self.main_controller.update_other_row_scrollbars(self, x_view_pos, args)
        if hasattr(self, 'canvas_manager'):
            self.canvas_manager.redraw()

    def sync_scroll(self, *args, x_view_pos=None):
        self.h_scrollbar.set(*args)
        if x_view_pos is not None:
            self.keysounds_canvas.xview_moveto(x_view_pos)
        if hasattr(self, 'canvas_manager'):
            self.canvas_manager.redraw()


class MainController(object):
    def __init__(self):
        self.opt_data = optimizer_data.OptimizerData(self.error_message)

        # State variables
        self.last_single_click_guid = None
        self.sync_scroll = True
        self.draw_substitute_keysounds = False

        # Build UI
        self.root = tk.Tk()
        self.root.title("Keysound Optimizer")
        self.root.resizable(True, True)
        self.root.geometry(f"{APP_WIDTH}x{APP_HEIGHT}")

        self.configure_menu_bar()

        self.right_panel = self.configure_right_panel()
        self.top_panel = self.configure_top_panel()

        self.error_label = tk.Label(self.root, 
            text="", fg="#900000", anchor='w', justify='left')
        self.error_label.pack(fill='x', pady=(1,0))


        self.scroll_frame = ScrollableFrame(self.root, self)
        self.scroll_frame.pack(fill="both", expand=True, padx=2, pady=(1,5))
        self.scroll_frame_viewport = None

        self.root.bind_all("<MouseWheel>", self.on_mousewheel_y)
        self.root.bind_all("<Shift-MouseWheel>", self.on_mousewheel_x)

        self.configure_hotkeys()
        self.refresh_rows()

    def on_mousewheel_y(self, event):
        self.scroll_frame.try_vertical_scroll(event)
        return 'break'

    def on_mousewheel_x(self, event):
        for row in self.rows:
            row.try_horizontal_scroll(event)
        return 'break'

    def error_message(self, text):
        self.error_label.config(text=text)
        self.root.update_idletasks()

    def configure_hotkeys(self):
        self.root.bind("<Control-o>", self._open_file)
        self.root.bind("<Control-e>", self._export_bms)

    def _try_get_track_selection_range(self, from_guid, to_guid):
        if from_guid is None: return None
        if to_guid is None: return None
        if not self.opt_data.is_track(from_guid): return None
        if not self.opt_data.is_track(to_guid): return None

        track_guids = [t.guid for t in self.opt_data.get_tracks()]
        if from_guid not in track_guids: return None
        if to_guid not in track_guids: return None
        from_index = track_guids.index(from_guid)
        to_index = track_guids.index(to_guid)
        to_select = [track_guids[i] for i in range(min(from_index,to_index),max(from_index,to_index)+1)]
        return to_select

    def track_selection_click(self, guid, holding_shift, holding_ctrl):
        guids_to_select = None
        if holding_shift:
            guids_to_select = self._try_get_track_selection_range(self.last_single_click_guid, guid)

        if guids_to_select is not None:
            if not holding_ctrl:
                self.opt_data.deselect_all()
            for guid_to_select in guids_to_select:
                self.opt_data.select_track(guid_to_select)
        else:
            self.last_single_click_guid = guid
            if holding_ctrl:
                # ctrl-only: toggle
                is_selected = self.opt_data.is_track_selected(guid)
                if is_selected:
                    self.opt_data.deselect_track(guid)
                else:
                    self.opt_data.select_track(guid)
            else:
                # no shift or ctrl: select single
                self.opt_data.deselect_all()
                self.opt_data.select_track(guid)

        self.refresh_selection()


    def _try_get_keysound_selection_range(self, from_guid, to_guid):
        if from_guid is None: return None
        if to_guid is None: return None
        if not self.opt_data.is_keysound(from_guid): return None
        if not self.opt_data.is_keysound(to_guid): return None

        track = self.opt_data.get_track_of_keysound(to_guid)
        keysound_guids = [t.guid for t in track.keysounds]
        if from_guid not in keysound_guids: return None
        if to_guid not in keysound_guids: return None
        from_index = keysound_guids.index(from_guid)
        to_index = keysound_guids.index(to_guid)
        to_select = [keysound_guids[i] for i in range(min(from_index,to_index),max(from_index,to_index)+1)]
        return to_select

    def keysound_selection_click(self, guid, holding_shift, holding_ctrl):
        guids_to_select = None
        if holding_shift:
            guids_to_select = self._try_get_keysound_selection_range(self.last_single_click_guid, guid)

        if guids_to_select is not None:
            if not holding_ctrl:
                self.opt_data.deselect_all()
            for guid_to_select in guids_to_select:
                self.opt_data.select_keysound(guid_to_select)
        else:
            self.last_single_click_guid = guid
            if holding_ctrl:
                # ctrl-only: toggle
                is_selected = self.opt_data.is_keysound_selected(guid)
                if is_selected:
                    self.opt_data.deselect_keysound(guid)
                else:
                    self.opt_data.select_keysound(guid)
            else:
                # no shift or ctrl: select single
                self.opt_data.deselect_all()
                self.opt_data.select_keysound(guid)
        self.refresh_selection()

    def configure_menu_bar(self):
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open (Ctrl+O)", command=self._open_file)
        file_menu.add_command(label="Export", command=self._export_bms)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)

        menubar.add_cascade(label="File", menu=file_menu)
        self.root.config(menu=menubar)

    def _open_file(self, event=None):
        selected_files = filedialog.askopenfilenames(
            title="Select Files",
            filetypes=[
                ('BMS Files', [f'*{ext}' for ext in BMS_EXTENSIONS]),
                ('SayaSlicer files', [f'*{ext}' for ext in SYP_EXTENSIONS])
            ]
        )
        optimizer_io.read_files(self.opt_data, selected_files)
        #messagebox.showinfo("Alert Title", "This is your alert message!")
        self.refresh_rows()

    def _export_bms(self, event=None):
        optimizer_io.open_export_window(self, self.opt_data)

    def configure_top_panel(self):
        top_panel = tk.Frame(self.root)
        top_panel.pack(side="top", fill='x', expand=False, padx=10, pady=(10,0))
        #top_panel.pack_propagate(False)

        tk.Button(
            top_panel, font=FONT_MAIN,
            text="Select All Keysounds",
            command=self._execute_then_refresh(self.opt_data.select_all_keysounds)
        ).pack(side='left', padx=5)

        tk.Button(
            top_panel, font=FONT_MAIN,
            text="Select All Tracks",
            command=self._execute_then_refresh(self.opt_data.select_all_tracks)
        ).pack(side='left', padx=5)

        tk.Button(
            top_panel, font=FONT_MAIN,
            text="Deselect All",
            command=self._execute_then_refresh(self.opt_data.deselect_all)
        ).pack(side='left', padx=5)

        tk.Frame(top_panel, width=3, bg="gray").pack(side='left', fill='y', padx=5)

        tk.Button(
            top_panel, font=FONT_MAIN,
            text="Make Group",
            command=self._execute_then_refresh(self.opt_data.group_selected_tracks)
        ).pack(side='left', padx=5)

        tk.Button(
            top_panel, font=FONT_MAIN,
            text="Separate Group",
            command=self._execute_then_refresh(self.opt_data.separate_selected_groups)
        ).pack(side='left', padx=5)

        tk.Button(
            top_panel, font=FONT_MAIN,
            text="Delete Tracks",
            command=self._execute_then_refresh(self.opt_data.delete_selected_tracks)
        ).pack(side='left', padx=5)

        return top_panel

    def _execute_then_refresh(self, fun):
        def f():
            fun()
            self.refresh_rows()
        return f

    def configure_right_panel(self):
        right_panel = tk.Frame(self.root, width=SIDE_PANEL_WIDTH)
        right_panel.pack_propagate(False)
        right_panel.pack(side="right", fill='y', expand=False, padx=2, pady=10)

        self.count_variables = {}
        class CounterLabel(object):
            def __init__(self, label, text):
                self.label = label
                self.text = text
                self.value = 0
                self.counters = None
            def initialize_counters(self, counters):
                self.counters = counters
            def set(self, value):
                self.value = value
                if self.counters is None: return
                label_text = self.text % tuple(c.value for c in self.counters)
                #print(label_text)
                self.label.configure(text=label_text)

        def counter_label(counter_names, text):
            if type(counter_names) is str:
                counter_names = (counter_names, )
            label = tk.Label(right_panel, text="", font=FONT_MAIN)
            label.pack(side="top")
            counters = tuple(CounterLabel(label, text) for c in counter_names)
            for counter_name, counter in zip(counter_names, counters):
                counter.initialize_counters(counters)
                self.count_variables[counter_name] = counter

        def double_button(label_header, button1, button2):
            if label_header is not None:
                tk.Label(right_panel, text=label_header, font=FONT_MAIN).pack(pady=(2,0), side="top")
            dbframe = tk.Frame(right_panel)
            dbframe.pack(side='top', padx=5)
            button1(dbframe).pack(side='left', padx=1)
            button2(dbframe).pack(side='right', padx=1)

        def single_button(button_text, command):
            tk.Button(right_panel, text=button_text, font=FONT_MAIN, command=command).pack(side='top', padx=5)
        
        class WidgetVariable(object):
            def __init__(self, var, widget, on_change):
                self.var = var
                self.widget = widget
                self.on_change = on_change
                
            def set(self, value):
                if isinstance(self.widget, ttk.Combobox):
                    old_state = self.widget.cget('state') 
                    self.widget.config(state='normal')
                    self._modify(value)
                    self.widget.config(state=old_state)
                else:
                    self._modify(value)

            def _modify(self, value):
                if value is None:
                    self.widget.delete(0, 'end') 
                else:
                    self.widget.delete(0, 'end')
                    self.widget.insert(0, str(value))

            def get(self, *args):
                try:
                    value = self.var.get()
                except:
                    return
                self.on_change(value)


        def spinbox(label_header, on_change, integer=False):
            var, spinbox, container = create_spinbox(right_panel, label_header, width=7, integer=integer)
            container.pack(side='top', fill='x', padx=5)
            widget_var = WidgetVariable(var, spinbox, on_change)
            var.trace_add("write", widget_var.get)
            return widget_var

        def combobox(label_header, on_change, options):
            #dbframe = tk.Frame(right_panel)
            #dbframe.pack(side='top', padx=5)
            tk.Label(right_panel, text=label_header, font=FONT_MAIN).pack(pady=(2,0), side="top")

            var = tk.StringVar()
            combo = ttk.Combobox(right_panel, textvariable=var, values=options, state='readonly', width=15)
            combo.pack(fill='x', side='top', padx=5)
            #combo.set(options[0])
            widget_var = WidgetVariable(var, combo, on_change)
            combo.bind("<<ComboboxSelected>>", widget_var.get)
            return widget_var

        def set_sync_scroll(value):
            def f():
                self.sync_scroll = value
            return f

        def switch_substitute_status(substitute):
            def f():
                self.draw_substitute_keysounds = substitute
                self.refresh_selection()
            return f

        def play_keysound(substitute):
            def f():
                selected_keysounds = self.opt_data.get_selected_keysounds()
                if len(selected_keysounds) != 1:
                    print(f'Error: {len(selected_keysounds)} keysounds selected')
                else:
                    keysound = next(iter(selected_keysounds))
                    audio_data = keysound.get_audio_data(substitute)
                    data, sample_rate = audio_data.get_data()
                    sd.play(data, sample_rate)
            return f

        def optimize(all_groups):
            def f():
                self.opt_data.compute_clusters(all_groups=all_groups)
                self.refresh_selection()
            return f


        ### TODO OPTIONS:
        # Downsample

        ###############################################################################
        tk.Frame(right_panel, height=3, bg="gray").pack(side='top', fill='x', pady=5)
        tk.Label(right_panel, text="Global", font=FONT_HEADER).pack(side="top")
        counter_label(('base_unique_keysounds', 'optimized_unique_keysounds'), "Uniq. KS: %d -> %d")

        double_button("Waveform Display",
            lambda p: tk.Button(p, text="Original", font=FONT_MAIN, command=switch_substitute_status(substitute=False)),
            lambda p: tk.Button(p, text="Substitute", font=FONT_MAIN, command=switch_substitute_status(substitute=True)),
        )

        double_button("Horizontal Scroll",
            lambda p: tk.Button(p, text="Joined", font=FONT_MAIN, command=set_sync_scroll(True)),
            lambda p: tk.Button(p, text="Separate", font=FONT_MAIN, command=set_sync_scroll(False)),
        )

        ###############################################################################
        tk.Frame(right_panel, height=3, bg="gray").pack(side='top', fill='x', pady=5)
        tk.Label(right_panel, text="Keysounds Panel", font=FONT_HEADER).pack(side="top")
        counter_label('num_selected_keysounds', "[ %d keysounds selected ]")
        counter_label('audio_distance', "%s")

        double_button("Play Keysound",
            lambda p: tk.Button(p, text="Original", font=FONT_MAIN, command=play_keysound(substitute=False)),
            lambda p: tk.Button(p, text="Substitute", font=FONT_MAIN, command=play_keysound(substitute=True)),
        )

        ###############################################################################
        tk.Frame(right_panel, height=3, bg="gray").pack(side='top', fill='x', pady=5)
        tk.Label(right_panel, text="Track Panel", font=FONT_HEADER).pack(side="top")
        counter_label('num_selected_tracks', "[ %d tracks selected ]")
        counter_label(('base_tracks_unique_keysounds', 'optimized_tracks_unique_keysounds'), "Uniq. KS: %d -> %d")

        ###############################################################################
        tk.Frame(right_panel, height=3, bg="gray").pack(side='top', fill='x', pady=5)
        tk.Label(right_panel, text="Group Panel", font=FONT_HEADER).pack(side="top")
        counter_label('num_selected_groups', "[ %d groups selected ]")
        counter_label(('base_groups_unique_keysounds', 'optimized_groups_unique_keysounds'), "Uniq. KS: %d -> %d")

        double_button(None,
            lambda p: tk.Button(p, text="Optimize", font=FONT_MAIN, command=optimize(all_groups=False)),
            lambda p: tk.Button(p, text="Optimize All", font=FONT_MAIN, command=optimize(all_groups=True)),
        )


        self.var_threshold = spinbox("Threshold",
            on_change=lambda v: self.opt_data.set_selected_group_property('threshold', v))

        self.var_weight_mfcc = spinbox("Weight (MFCC)",
            on_change=lambda v: self.opt_data.set_selected_group_property('weight_mfcc', v))
        self.var_weight_temporal = spinbox("Weight (Temporal)",
            on_change=lambda v: self.opt_data.set_selected_group_property('weight_temporal', v))
        self.var_weight_volume = spinbox("Weight (Volume)",
            on_change=lambda v: self.opt_data.set_selected_group_property('weight_volume', v))
        self.var_weight_brightness = spinbox("Weight (Brightness)",
            on_change=lambda v: self.opt_data.set_selected_group_property('weight_brightness', v))
        self.var_weight_pitch = spinbox("Weight (Pitch)",
            on_change=lambda v: self.opt_data.set_selected_group_property('weight_pitch', v))

        self.var_mfcc_size = spinbox("MFCC size",
            on_change=lambda v: self.opt_data.set_selected_group_property('mfcc_size', v), integer=True)

        self.var_metric = combobox("Metric",
            on_change=lambda v: self.opt_data.set_selected_group_property('metric', v), 
            options=[
                "euclidean",
                "manhattan",
                "chebyshev",
                "seuclidean",
                "mahalanobis",
        ])
        self.var_algorithm = combobox("Algorithm",
            on_change=lambda v: self.opt_data.set_selected_group_property('algorithm', v),
            options=[
                "weighted_dominating_set",
        ])
        self._update_ui_variables()

        return right_panel

    def _update_ui_variables(self):
        keysound_properties = [
            #('substitute_audio_data_id', self.substitute_audio_data_id),
            #('locked', self.locked),
        ]
        track_properties = [
            #('cursor_position', self.var_cursor_position),
        ]
        group_properties = [
            ('threshold', self.var_threshold),
            ('weight_mfcc', self.var_weight_mfcc),
            ('weight_temporal', self.var_weight_temporal),
            ('weight_volume', self.var_weight_volume),
            ('weight_brightness', self.var_weight_brightness),
            ('weight_pitch', self.var_weight_pitch),
            ('mfcc_size', self.var_mfcc_size),
            ('metric', self.var_metric),
            ('algorithm', self.var_algorithm),
        ]

        for property_name, variable in keysound_properties:
            variable.set(self.opt_data.get_selected_keysound_property(property_name))
        for property_name, variable in track_properties:
            variable.set(self.opt_data.get_selected_track_property(property_name))
        for property_name, variable in group_properties:
            variable.set(self.opt_data.get_selected_group_property(property_name))

        for property_name, count in self.opt_data.compute_counters().items():
            if property_name in self.count_variables:
                self.count_variables[property_name].set(count)

    def update_other_row_scrollbars(self, source, x_view_pos, args):
        if not self.sync_scroll: return
        for row in self.rows:
            if row is source:
                continue
            row.sync_scroll(*args, x_view_pos=x_view_pos)

    def refresh_rows(self):
        # Clear existing rows
        for widget in self.scroll_frame.scrollable_content.winfo_children():
            widget.destroy()
        self.rows = []

        track_groups = self.opt_data.get_track_groups()
        #tracks = self.opt_data.get_tracks()

        spacer_indices = [] # indices where you put a spacer before the next row.
        for group in track_groups:
            for track in group.tracks:
                row = RowWidget(self, self.scroll_frame.scrollable_content, self.opt_data, track)
                self.rows.append(row)

        spacer_indices = list(itertools.accumulate([len(g.tracks) for g in track_groups]))
        spacer_indices = set(spacer_indices[:-1])

        #for row in self.rows: row.pack_forget() # not needed as we have deleted the rows
        for index, row in enumerate(self.rows):
            pady_top, pady_bot = 1, 1
            if index == 0:
                pady_top = 15
            elif index == len(self.rows) - 1:
                pady_bot = 15
            elif index in spacer_indices:
                #pady_top = 5
                tk.Frame(self.scroll_frame.scrollable_content, height=2, bg="black").pack(fill='x', padx=2, pady=(10,10))
            row.pack(fill="x", padx=10, pady=(pady_top, pady_bot))

        self.refresh_selection()

    def refresh_selection(self):
        for row in self.rows:
            row.refresh_selection_appearance()
        self._redraw_group_boxes()
        self._update_ui_variables()
        self._recompute_scroll_frame_viewport()
        #self.root.after(0, self._redraw_group_boxes)

    UNSELECTED_GROUP_COLOR = '#606080'
    SELECTED_GROUP_COLOR = '#e080a0'
    def _redraw_group_boxes(self):
        track_groups = self.opt_data.get_track_groups()
        next_i = 0
        group_indices = []
        for group in track_groups:
            group_size = len(group.tracks)
            group_indices.append(list(range(next_i, next_i+group_size)))
            next_i += group_size

        canvas = self.scroll_frame.scrollable_content
        canvas.delete("group_box")  # remove old boxes

        canvas.update_idletasks() # force geometry update to get accurate target coordinates
        
        for group, index in zip(track_groups, group_indices):
            if len(index) <= 0: continue
            group_is_selected = any(self.opt_data.is_track_selected(track.guid) for track in group.tracks)
            pos_top = min(self.rows[i].winfo_y() for i in index)
            pos_bottom = max(self.rows[i].winfo_y() + self.rows[i].winfo_height() for i in index)
                
            x0 = 7
            y0 = pos_top - 3
            x1 = canvas.winfo_width() - 7
            y1 = pos_bottom + 3
            
            rect_id = canvas.create_rectangle(
                x0, y0, x1, y1, 
                outline = MainController.SELECTED_GROUP_COLOR if group_is_selected else MainController.UNSELECTED_GROUP_COLOR,
                width = 3 if group_is_selected else 2,
                tags = "group_box"
            )
            # lower the rectangle below the rows so it doesn't block interactions
            canvas.tag_lower(rect_id)

    def _recompute_scroll_frame_viewport(self):
        self.scroll_frame.canvas.update_idletasks()
        view_y1 = self.scroll_frame.canvas.canvasy(0)
        view_y2 = self.scroll_frame.canvas.canvasy(self.scroll_frame.canvas.winfo_height())
        self.scroll_frame_viewport = view_y1, view_y2

    def get_scroll_frame_viewport(self):
        if self.scroll_frame_viewport is None:
            self._recompute_scroll_frame_viewport()
        return self.scroll_frame_viewport
        
    def start(self):
        self.root.mainloop()
        
def main():
    main_controller = MainController()
    configure_styles()
    main_controller.start()
    

if __name__ == '__main__':
    main()
