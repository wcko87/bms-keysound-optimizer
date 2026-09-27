import os, sys
import libs.bms_io as bmsio
import syp_parser
from enum import Enum
from utils import *
from collections import OrderedDict, namedtuple
from types import SimpleNamespace
from fractions import Fraction
from natsort import natsorted

import tkinter as tk
from tkinter import ttk
from tkinter import filedialog
from tkinter import messagebox

class OptimizerIO(object):
    def __init__(self, opt_data):
        self.opt_data = opt_data

    def read_bms(self, file_path):
        print('read bms %s' % file_path)
        bms = bmsio.parse_from_file(file_path)
        self.opt_data.add_bms_file(bms, file_path)

        # add track for each measure_lane
        notes_by_measure_lane = {}
        for note in bms.all_objects:
            if note.measure_lane.lane not in notes_by_measure_lane:
                notes_by_measure_lane[note.measure_lane.lane] = []
            notes_by_measure_lane[note.measure_lane.lane].append(note)
        notes_by_lane = [
            (lane, sorted(notes))
            for lane, notes in notes_by_measure_lane.items()
        ]
        notes_by_lane = natsorted(notes_by_lane, key=lambda pair: pair[0])

        bms_hash = compute_md5_hash(bms)
        audio_data_loader = self.opt_data.get_audio_data_loader()
        for lane, notes in notes_by_lane:
            if not bmsio.utils.is_keysound_note_lane(lane): continue
            keysound_datas = []
            for note in notes:
                audio_data = audio_data_loader.from_bms(file_path, bms, bms_hash, note.name)
                ms_from_start = _bms_to_ms_from_start(bms, note.measure_lane.measure_no, note.frac)
                keysound_datas.append((audio_data, ms_from_start)) 
            keysounds = self.opt_data.add_track(lane, keysound_datas)
            for note, keysound in zip(notes, keysounds):
                self.opt_data.add_bms_note_keysound_assignment(bms_hash, note, keysound)


    def read_syp(self, file_path):
        syp_data = syp_parser.SypData(file_path)
        # a little more complicated than expeected due to needing to apply volume filters
        # I do want to filter silent keysounds, so it may be best to add controls for this.


## Reads selected files into opt_data
def read_files(opt_data, selected_files):
    optimizer_io = OptimizerIO(opt_data)
    for file_path in selected_files:
        root, extension = os.path.splitext(file_path)
        if extension in BMS_EXTENSIONS:
            print(file_path, root, extension)
            optimizer_io.read_bms(file_path)
        elif extension in SYP_EXTENSIONS:
            optimizer_io.read_syp(file_path)

def _bms_to_ms_from_start(bms, measure, frac):
    ## TODO: move this into bmsio and let it be a timeline instead of a single bpm
    bpm = float(bms.metadata.properties['BPM'])
    return _bpm_to_ms_from_start(bpm, measure, frac)

def _bpm_to_ms_from_start(bpm, measure, frac):
    return float((measure + frac)*1000*60*4/bpm)

def _to_measure_frac(bpm, ms_from_start, limit_denominator=10_000):
    ## TODO: move this into bmsio and let it be a timeline instead of a single bpm
    # bpm = beats per minute
    # 1000 ms per second
    # 60 second per minute
    # 4 beats per measure
    # bpm/4/60/1000 measures per ms
    measures_frac = Fraction(ms_from_start*bpm/4/60/1000).limit_denominator(limit_denominator)
    return measures_frac//1, measures_frac%1


"""
Some planned policies:
- track order (collapsed)
- track order (spaced - grouping by track)
- original keysound ids
- original keysound id order (collapsed)
- original keysound id order (spaced - grouping by clusters of keysounds?)
- lexicographical order (collapsed)
- lexicographical order (spaced - grouping by clusters of words?)
"""
class AssignmentPolicy(Enum):
    TRACK_ORDER_COLLAPSED = "Track Order (Collapsed)"
    ORIGINAL_KEYSOUNDS_COLLAPSED = "Original Keysounds (Collapsed)"

KEYSOUND_POLICY_FUNCTIONS = {
    AssignmentPolicy.TRACK_ORDER_COLLAPSED: '_policy_track_order_collapsed',
    AssignmentPolicy.ORIGINAL_KEYSOUNDS_COLLAPSED: '_policy_original_keysounds_collapsed',
}
class KeysoundAssigner(object):
    def __init__(self, policy=None):
        if policy is None: 
            policy = AssignmentPolicy.TRACK_ORDER_ORIGINAL
        self._policy_function = getattr(self, KEYSOUND_POLICY_FUNCTIONS[policy])
        self._keysound_index_to_id = to_base36

        self._used_file_names = set()

        # -- OUTPUTS --
        # optimizer keysound guid -> keysound_id (01-ZZ)
        self.keysound_guid_to_keysound_id_str = {}
        # keysound_id (01-ZZ) -> export file name (extensionless)
        self.keysound_id_str_to_file_name = {}
        # keysound_id (01-ZZ) -> IAudioData (for export)
        self.keysound_id_str_to_audio_data = {}
        # audio_data_id -> keysound_id (01-ZZ)
        self.audio_data_id_to_keysound_id_str = {}

    def compute_assignments(self, tracks_keysounds, existing_bms=None):
        tracks_keysounds = sorted(tracks_keysounds, key=lambda p: p[0])
        audio_data_dict = self._process_audio_datas(tracks_keysounds)
        self._policy_function(audio_data_dict, existing_bms=None)
        return self

    def _generate_file_name(self, audio_data):
        file_name = audio_data.suggest_file_name()
        if file_name is None:
            file_name = ''

        if file_name.lower().endswith(AUDIO_EXTENSIONS):
            file_name = file_name[:file_name.rfind('.')]

        while file_name in self._used_file_names:
            match = re.search(r"_(\d+)$", file_name)
            if match:
                # increment trailing number
                num_str = match.group(1)
                file_name = text[:match.start(1)] + str(int(num_str)+1).zfill(len(num_str))
            else:
                # include trailing number
                file_name = file_name + '_1'
        
        self._used_file_names.add(file_name)
        return file_name

    def _process_audio_datas(self, tracks_keysounds):
        # audio_data_id -> AudioDataInfo
        audio_data_dict = OrderedDict()
        class AudioDataInfo:
            def __init__(self, audio_data):
                self.audio_data = audio_data
                self.keysounds = []
                self.keysound_file_name = None

        for index, track, keysound in tracks_keysounds:
            audio_data = keysound.get_audio_data(substitute=True)
            if audio_data.id not in audio_data_dict:
                audio_data_dict[audio_data.id] = AudioDataInfo(audio_data=audio_data)
            audio_data_dict[audio_data.id].keysounds.append((index, track, keysound))

        # separate loop for generating file names just in case we want a more complex collision resolution
        for audio_data_id, audio_data_info in audio_data_dict.items():
            audio_data = audio_data_info.audio_data
            audio_data_info.keysound_file_name = self._generate_file_name(audio_data)

        return audio_data_dict

    def _generate_outputs(self, audio_data_dict, keysound_id_strs):
        self.keysound_id_str_to_file_name = OrderedDict()
        self.keysound_guid_to_keysound_id_str = OrderedDict()
        self.keysound_id_str_to_audio_data = OrderedDict()
        self.audio_data_id_to_keysound_id_str = OrderedDict()

        for audio_data_id, audio_data_info in audio_data_dict.items():
            keysound_id_str = keysound_id_strs[audio_data_id]
            keysound_filename_without_ext, ext = os.path.splitext(audio_data_info.keysound_file_name)
            self.keysound_id_str_to_file_name[keysound_id_str] = keysound_filename_without_ext
            self.keysound_id_str_to_audio_data[keysound_id_str] = audio_data_info.audio_data

            for index, track, keysound in audio_data_info.keysounds:
                self.keysound_guid_to_keysound_id_str[keysound.guid] = keysound_id_str


    def _policy_track_order_collapsed(self, audio_data_dict, existing_bms=None):
        next_keysound_index = 1
        keysound_id_strs = {}
        for audio_data_id in audio_data_dict:
            keysound_id_str = self._keysound_index_to_id(next_keysound_index)
            next_keysound_index += 1
            keysound_id_strs[audio_data_id] = keysound_id_str

        self._generate_outputs(audio_data_dict, keysound_id_strs)

    def _policy_original_keysounds_collapsed(self, audio_data_dict, existing_bms=None):
        if existing_bms is None:
            return self._policy_track_order_collapsed(audio_data_dict, existing_bms)

        audio_data_dict_reserved = OrderedDict()
        audio_data_dict_free = OrderedDict()

        bms_hash = compute_md5_hash(existing_bms)
        for audio_data_id, item in audio_data_dict.items():
            if isinstance(item.audio_data, BMSAudioData) and item.audio_data.bms_hash == bms_hash:
                audio_data_dict_reserved[audio_data_id] = item
            else:
                audio_data_dict_free[audio_data_id] = item

        keysound_id_strs = {}
        reserved_keysound_ids = set()
        for audio_data_id, item in audio_data_dict_reserved.items():
            keysound_id_str = audio_data.keysound_id
            reserved_keysound_ids.add(keysound_id_str)
            keysound_id_strs[audio_data_id] = keysound_id_str

        next_keysound_index = 1
        for audio_data_id, item in audio_data_dict_free.items():
            while True:
                keysound_id_str = self._keysound_index_to_id(next_keysound_index)
                next_keysound_index += 1
                if keysound_id_str not in reserved_keysound_ids:
                    keysound_id_strs[audio_data_id] = keysound_id_str
                    break

        self._generate_outputs(audio_data_dict, keysound_id_strs)


class BMSExporter(object):
    def __init__(self, opt_data, ks_assg_policy=None, existing_bms=None, start_bpm=None):
        self.opt_data = opt_data
        self.existing_bms = existing_bms
        self.start_bpm = start_bpm
        self.ks_assg_policy = ks_assg_policy

    def export(self, output_folder, output_bms_name='optimizer_output.bms'):
        self._compute_keysound_id_assignments()
        self._export_to_bms(output_folder, output_bms_name)
        self._export_keysounds(output_folder)

    def _compute_keysound_id_assignments(self):
        tracks = self.opt_data.get_tracks()
        tracks_keysounds = []
        for index, track in enumerate(tracks):
            for keysound in track.keysounds:
                tracks_keysounds.append((index, track, keysound))

        self.assigner = KeysoundAssigner(self.ks_assg_policy)
        self.assigner.compute_assignments(tracks_keysounds, self.existing_bms)

    def _export_keysounds(self, output_folder):
        for keysound_id_str, file_name in self.assigner.keysound_id_str_to_file_name.items():
            audio_data = self.assigner.keysound_id_str_to_audio_data[keysound_id_str]
            audio_data.export_to_file(output_folder, file_name)

    def _get_note_to_keysound_id_mapping(self, opt_data, existing_bms, assignment_by_keysound_guid):
        assert existing_bms is not None
        # note -> (keysound, keysound_id)
        assignment_by_note = {}
        bms_hash = compute_md5_hash(existing_bms)
        for note in existing_bms.all_objects:
            if not bmsio.utils.is_keysound_note_lane(note.measure_lane.lane): continue
            keysound = self.opt_data.get_bms_note_assigned_keysound(bms_hash, note)
            assigned_keysound_id = assignment_by_keysound_guid[keysound.guid]
            assignment_by_note[note] = (keysound, assigned_keysound_id)
        return assignment_by_note

    def _export_to_bms(self, output_folder, output_bms_name):
        #1. use bmsio to duplicate existing bms
        if self.existing_bms is None:
            ## TODO: expand to more than just a single fixed bpm.
            # this should have bpm changes and time signature.
            new_bms = bmsio.BMS({})
        else:
            new_bms = bmsio.BMS(self.existing_bms.metadata)
        if self.start_bpm is not None:
            new_bms.metadata.properties['BPM'] = self.start_bpm
        bpm = new_bms.metadata.properties['BPM']

        new_bms.metadata.keysounds = OrderedDict([
            (keysound_id_str, self.assigner.keysound_id_str_to_file_name[keysound_id_str] + '.wav')
            for keysound_id_str in sorted(self.assigner.keysound_id_str_to_file_name.keys())
        ])

        # keysound obj guid -> keysound_id
        assignment_by_keysound_guid = self.assigner.keysound_guid_to_keysound_id_str

        already_processed_keysound_guids = set()
        if self.existing_bms is not None:
            # generate from bms note objs
            # bms note -> optimizer.keysound obj (if bms exists)
            assignment_by_note = self._get_note_to_keysound_id_mapping(self.opt_data, self.existing_bms, assignment_by_keysound_guid)
            for note in self.existing_bms.all_objects:
                if not bmsio.utils.is_keysound_note_lane(note.measure_lane.lane):
                    new_bms.copy_note(note)
                    continue
                pair = assignment_by_note.get(note)
                if pair is not None:
                    keysound, new_keysound_id = pair
                    new_bms.copy_note(note, name=new_keysound_id)
                    already_processed_keysound_guids.add(keysound.guid)
                else:
                    print(f'Note with missing keysound id mapping: {note}')

        # generate from keysound objs
        tracks = self.opt_data.get_tracks()
        for index, track in enumerate(tracks):
            lane = 'B%d' % (index+1)
            for keysound in track.keysounds:
                if keysound.guid in already_processed_keysound_guids: continue
                measure, frac = _to_measure_frac(bpm, keysound.get_ms_from_start())
                new_keysound_id = assignment_by_keysound_guid[keysound.guid]
                new_bms.add_note(measure, lane, new_keysound_id, frac.numerator, frac.denominator)

        # TODO: future: custom time signatures (and bpms)
        new_bms.time_signatures = self.existing_bms.time_signatures.copy()

        with open(os.path.join(output_folder, output_bms_name), 'w+', encoding='shift-jis') as f:
            f.write(new_bms.to_string())



def open_export_window(main_controller, opt_data):
    export_win = tk.Toplevel(main_controller.root)
    export_win.title("Export Settings")
    export_win.geometry("400x300")
    
    export_win.lift()          # Bring to front
    export_win.focus_force()   # Force focus onto the window
    export_win.grab_set()      # Make it modal (lock main window)
    
    main_frame = ttk.Frame(export_win, padding="20")
    main_frame.pack(fill=tk.BOTH, expand=True)

    def list_get(li, index):
        return li[index] if index < len(li) else None

    # Combobox for BMS Selection
    ttk.Label(main_frame, text="Select Base BMS:").pack(anchor=tk.W, pady=(0, 5))
    bms_datas = opt_data.get_bms_datas()
    if len(bms_datas) <= 0:
        export_win.destroy()
        messagebox.showwarning("Warning", "No base BMS file loaded", parent=main_controller.root)
        return
    combo_base_bms = ttk.Combobox(main_frame, values=[bd.bms_file_name for bd in bms_datas], state="readonly")
    combo_base_bms.pack(fill='x', pady=(0, 15))
    combo_base_bms.current(0)
    get_combo_base_bms = lambda: list_get(bms_datas, combo_base_bms.current())

    # Combobox for Keysound Assignment Policy
    ttk.Label(main_frame, text="Select Scope:").pack(anchor=tk.W, pady=(0, 5))
    assignment_policies = list(AssignmentPolicy)
    combo_ks_assg_policy = ttk.Combobox(main_frame, values=[policy.value for policy in assignment_policies], state="readonly")
    combo_ks_assg_policy.pack(fill='x', pady=(0, 20))
    combo_ks_assg_policy.current(0)
    get_combo_ks_assg_policy = lambda: list_get(assignment_policies, combo_ks_assg_policy.current())

    # File browser to select path
    def select_destination():
        file_path = filedialog.asksaveasfilename(
            defaultextension=".bms",
            filetypes=[("BMS File", "*.bms")],
            title="Output BMS File"
        )
        if file_path:
            selected_path_var.set(file_path)
            path_label.config(foreground="black")

    selected_path_var = tk.StringVar(value="No file selected")
    path_label = ttk.Label(main_frame, textvariable=selected_path_var, foreground="gray", wraplength=350)
    file_btn = ttk.Button(main_frame, text="Select Destination & Name File", command=select_destination)
    file_btn.pack(fill='x', pady=(0, 5))
    path_label.pack(anchor=tk.W, pady=(0, 20))

    def confirm_export():
        path = selected_path_var.get()
        bms_choice = get_combo_base_bms().bms_data
        ks_assg_policy_choice = get_combo_ks_assg_policy()

        if path == "No file selected" or not path:
            messagebox.showwarning("Warning", "Please select a file destination first!", parent=export_win)
            return
        if bms_choice is None:
            messagebox.showwarning("Warning", "Please select a valid BMS file as a base", parent=export_win)
            return
        if ks_assg_policy_choice is None:
            messagebox.showwarning("Warning", "Please select a keysound assignment policy", parent=export_win)
            return

        bms_exporter = BMSExporter(opt_data,
            ks_assg_policy=ks_assg_policy_choice,
            existing_bms=bms_choice,
            start_bpm=float(bms_choice.metadata.properties['BPM']),
        )
        folder, filename = os.path.split(path)
        bms_exporter.export(
            output_folder=folder,
            output_bms_name=filename,
        )

        messagebox.showinfo("Success", "File exported successfully!", parent=export_win)
        export_win.destroy()

    confirm_btn = ttk.Button(main_frame, text="Export to BMS", command=confirm_export)
    confirm_btn.pack(side=tk.BOTTOM, fill='x')
