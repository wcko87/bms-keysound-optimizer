from sklearn.preprocessing import StandardScaler
from collections import OrderedDict, namedtuple
from audio_data import AudioDataLoader
from utils import *
import os
import keysound_clustering

class GUIDGenerator(object):
    NULL_GUID = 0

    def __init__(self):
        self.next_guid = 1

    @staticmethod
    def is_null(guid):
        return guid == GUIDGenerator.NULL_GUID

    def generate_keysound_guid(self):
        guid = self.next_guid
        self.next_guid += 1
        return guid

    def generate_track_guid(self):
        guid = self.next_guid
        self.next_guid += 1
        return guid

class Keysound(object):
    def __init__(self, audio_data_loader, guid, track_guid, audio_data, ms_from_start):
        self.audio_data_loader = audio_data_loader
        self.guid = guid
        self.track_guid = track_guid
        self._audio_data = audio_data
        self._ms_from_start = ms_from_start

        self.properties = {
            'substitute_audio_data_id': None,
            'locked': False,
        }

    def has_substitution(self):
        return self.properties['substitute_audio_data_id'] is not None and self._audio_data.id != self.properties['substitute_audio_data_id']

    """   TODO: REMOVE
    def set_last_substitution_audio_distance(self, value):
        self.last_substitution_audio_distance = value

    def get_last_substitution_audio_distance(self):
        return self.last_substitution_audio_distance

        # Future TODO: dynamically compute problem is that X requires all audio feature vectors at once
        if not self.has_substitution(): return 0.0
        fvec1 = self.get_audio_data(substitute=True).get_already_computed_feature_vector()
        fvec2 = self.get_audio_data(substitute=False).get_already_computed_feature_vector()
        if fvec1 is None or fvec2 is None: return 0.0
        return optimizer.clustering.

    """

    def set_substitute(self, audio_data_id):
        self.properties['substitute_audio_data_id'] = audio_data_id

    def get_audio_data(self, substitute=False):
        if not substitute or self.properties['substitute_audio_data_id'] is None:
            return self._audio_data
        return self.audio_data_loader.get_audio_data(self.properties['substitute_audio_data_id'])

    def get_ms_from_start(self):
        return self._ms_from_start

class Track(object):
    def __init__(self, guid, track_name, keysounds):
        self.guid = guid
        self.keysounds = keysounds
        self.track_name = track_name
        self.sort_keysounds()

        self.properties = {
            'cursor_position': 0,
        }

    def sort_keysounds(self):
        self.keysounds.sort(key = lambda keysound: keysound.get_ms_from_start())

class TrackGroup(object):
    def __init__(self, tracks):
        self.tracks = tracks

        self.properties = {
            'threshold': 1.0,
            "weight_mfcc": 1.5,
            "weight_temporal": 3.0,
            "weight_volume": 0.5,
            "weight_brightness": 0.5,
            "weight_pitch": 50.0,
            'mfcc_size': 13,
            'metric': 'euclidean',
            'algorithm': 'weighted_dominating_set',
        }

    def remove_tracks(self, to_remove):
        to_remove_set = set(to_remove)
        self.tracks = [track for track in self.tracks if track.guid not in to_remove_set]

    def properties_match(self, other_group):
        return self.properties == other_group.properties

    def inherit_properties(self, other_group):
        self.properties = {key: other_group.properties[key] for key in self.properties.keys()}


class OptimizerData(object):
    def __init__(self, log_func):
        self.log = log_func

        # main data
        self._track_groups = []
        self._open_bms_files = OrderedDict()
        self._bms_note_keysound_assignment = {}

        # selection state
        self._selected_keysounds = set()
        self._selected_tracks = set()

        # miscellaneous helper variables
        self._guid_generator = GUIDGenerator()
        self._guid_to_keysound = {}
        self._guid_to_track = {}
        self._track_groups_modified = True
        self._audio_data_loader = AudioDataLoader()

        # clustering data
        self._last_clustering_distance_query = None

    def add_bms_note_keysound_assignment(self, bms_hash, note, keysound):
        self._bms_note_keysound_assignment[(bms_hash, note)] = keysound

    def get_bms_note_assigned_keysound(self, bms_hash, note):
        return self._bms_note_keysound_assignment[(bms_hash, note)]

    def get_audio_data_loader(self):
        return self._audio_data_loader

    def add_bms_file(self, bms_data, file_path):
        bms_hash = compute_md5_hash(bms_data)
        bms_file_name = os.path.basename(file_path)
        if bms_hash not in self._open_bms_files:
            self._open_bms_files[bms_hash] = (bms_data, bms_file_name)
        print(f'Added bms file: {bms_hash}')

    def remove_bms_file(self, bms_hash):
        if bms_hash in self._open_bms_files:
            del self._open_bms_files[bms_hash]

    def clear_bms_files(self):
        self._open_bms_files = []

    def get_bms_datas(self):
        BMSData = namedtuple("BMSData", ["bms_hash", "bms_data", "bms_file_name"])
        return [BMSData(k, v[0], v[1]) for k, v in self._open_bms_files.items()]

    def add_track(self, track_name, keysound_datas):
        track_guid = self._guid_generator.generate_track_guid()
        keysounds = []
        for audio_data, ms_from_start in keysound_datas:
            keysound_guid = self._guid_generator.generate_keysound_guid()
            keysounds.append(Keysound(self._audio_data_loader, keysound_guid, track_guid, audio_data, ms_from_start))
        track = Track(track_guid, track_name, keysounds)
        self._track_groups.append(TrackGroup([track]))
        self.set_track_groups_modified_flag()
        print(f'Track {track_name}: {len(keysounds)} keysounds') # QWEQWEQWE
        return keysounds

    def refresh_guid_mappings(self):
        if not self._track_groups_modified: return
        self._guid_to_keysound = {}
        self._guid_to_track = {}
        for group in self._track_groups:
            for track in group.tracks:
                self._guid_to_track[track.guid] = track
                for keysound in track.keysounds:
                    self._guid_to_keysound[keysound.guid] = keysound
        self._track_groups_modified = False

    def set_track_groups_modified_flag(self):
        self._track_groups_modified = True

    def is_keysound_selected(self, guid):
        return guid in self._selected_keysounds

    def is_track_selected(self, guid):
        return guid in self._selected_tracks

    def _get_selected_groups(self):
        return [
            group for group in self._track_groups 
            if any(self.is_track_selected(track.guid) for track in group.tracks)
        ]

    def separate_selected_groups(self):
        while True:
            to_split = None
            for index, track_group in enumerate(self._track_groups):
                if len(track_group.tracks) <= 1: continue
                if any(self.is_track_selected(track.guid) for track in track_group.tracks):
                    to_split = index
                    break
            if to_split is not None:
                new_groups = [TrackGroup([track]) for track in self._track_groups[index].tracks]
                for track_group in new_groups:
                    track_group.inherit_properties(self._track_groups[index])
                self._track_groups = self._track_groups[:index] + new_groups + self._track_groups[index+1:]
            else:
                break
        self.set_track_groups_modified_flag()

    def get_group_selected_tracks_warnings(self):
        current_groups = self._get_selected_groups()
        if len(current_groups) <= 0: return []

        warnings = []
        if len(current_groups) > 1:
            for group in current_groups[1:]:
                if not current_group.properties_match(group):
                    warnings.append(WARNING_NONMATCHING_GROUPS)
                    break
        for group in current_groups:
            if any(not self.is_track_selected(track.guid) for track in group.tracks):
                warnings.append(WARNING_SPLITTING_GROUPS)
                break
        return warnings

    def group_selected_tracks(self):
        current_groups = self._get_selected_groups()
        if len(current_groups) <= 0: return

        new_group_tracks = []
        first_group = current_groups[0]
        insert_index = None

        new_groups = []
        for group in self._track_groups:
            to_remove = [track.guid for track in group.tracks if self.is_track_selected(track.guid)]
            new_group_tracks += [track for track in group.tracks if self.is_track_selected(track.guid)]
            if len(to_remove) < len(group.tracks):
                new_groups.append(group)
            if len(to_remove) > 0:
                group.remove_tracks(to_remove)
                # to_remove is guaranteed to be non-empty at least once.
                if insert_index is None:
                    insert_index = len(new_groups)
                    new_groups.append(None)

        new_group = TrackGroup(new_group_tracks)
        new_group.inherit_properties(first_group)
        new_groups[insert_index] = new_group

        self._track_groups = new_groups
        self.set_track_groups_modified_flag()

    def delete_selected_tracks(self):
        self._delete_tracks(self, self._selected_tracks)

    def _delete_tracks(self, to_delete):
        to_delete_set = set(to_delete)
        new_groups = []
        for group in self._track_groups:
            delete_from_group = [track.guid for track in group.tracks if (track.guid in to_delete_set)]
            if len(delete_from_group) < len(group.tracks):
                new_groups.append(group)
            if len(delete_from_group) > 0:
                group.remove_trakcs(delete_from_group)

        self._track_groups = new_groups
        self.set_track_groups_modified_flag()

    def get_track_groups(self):
        return self._track_groups

    def get_tracks(self):
        return [track for group in self._track_groups for track in group.tracks]

    def _get_selected_tracks(self):
        self.refresh_guid_mappings()
        return [self._guid_to_track[guid] for guid in self._selected_tracks]

    def is_track(self, guid):
        self.refresh_guid_mappings()
        return guid in self._guid_to_track

    def select_track(self, guid):
        self._selected_tracks.add(guid)

    def deselect_track(self, guid):
        if guid in self._selected_tracks:
            self._selected_tracks.remove(guid)

    def select_all_tracks(self):
        self._selected_tracks = {track.guid for track in self.get_tracks()}

    def _get_keysounds(self):
        return [keysound for track in self.get_tracks() for keysound in track.keysounds]

    def get_selected_keysounds(self):
        self.refresh_guid_mappings()
        return [self._guid_to_keysound[guid] for guid in self._selected_keysounds]

    def is_keysound(self, guid):
        self.refresh_guid_mappings()
        return guid in self._guid_to_keysound

    def get_keysound(self, guid):
        self.refresh_guid_mappings()
        return self._guid_to_keysound[guid]

    def get_track_of_keysound(self, guid):
        self.refresh_guid_mappings()
        track_guid = self._guid_to_keysound[guid].track_guid
        return self._guid_to_track[track_guid]

    def get_keysounds_of_track(self, guid):
        self.refresh_guid_mappings()
        return self._guid_to_track[guid].keysounds

    def select_keysound(self, guid):
        self.refresh_guid_mappings()
        self._selected_keysounds.add(guid)
        self._selected_tracks.add(self._guid_to_keysound[guid].track_guid)

    def deselect_keysound(self, guid):
        if guid in self._selected_keysounds:
            self._selected_keysounds.remove(guid)

    def select_all_keysounds(self):
        self._selected_keysounds = {keysound.guid for keysound in self._get_keysounds()}
        self.select_all_tracks()

    def deselect_all(self):
        self._selected_tracks.clear()
        self._selected_keysounds.clear()

    def _get_generic_property(self, property_dicts, property_name):
        values = [properties[property_name] for properties in property_dicts]
        if len(values) == 0: return None
        if all(v == values[0] for v in values):
            return values[0]
        return None

    def _set_generic_property(self, property_dicts, property_name, value):
        for properties in property_dicts:
            assert(property_name in properties)
            properties[property_name] = value

    def get_selected_group_property(self, property_name):
        property_dicts = [group.properties for group in self._get_selected_groups()]
        return self._get_generic_property(property_dicts, property_name)

    def set_selected_group_property(self, property_name, value):
        property_dicts = [group.properties for group in self._get_selected_groups()]
        self._set_generic_property(property_dicts, property_name, value)

    def get_selected_track_property(self, property_name):
        self.refresh_guid_mappings()
        property_dicts = [self._guid_to_track[guid].properties for guid in self._selected_tracks]
        return self._get_generic_property(property_dicts, property_name)

    def set_selected_track_property(self, property_name, value):
        self.refresh_guid_mappings()
        property_dicts = [self._guid_to_track[guid].properties for guid in self._selected_tracks]
        self._set_generic_property(property_dicts, property_name, value)

    def get_selected_keysound_property(self, property_name):
        self.refresh_guid_mappings()
        property_dicts = [self._guid_to_keysound[guid].properties for guid in self._selected_keysounds]
        return self._get_generic_property(property_dicts, property_name)

    def set_selected_keysound_property(self, property_name, value):
        self.refresh_guid_mappings()
        property_dicts = [self._guid_to_keysound[guid].properties for guid in self._selected_keysounds]
        self._set_generic_property(property_dicts, property_name, value)

    def get_keysound_track_options(self):
        return [(track.name, track.guid) for group in self._track_groups for track in group.tracks]

    def get_selected_keysounds_track(self):
        self.refresh_guid_mappings()
        values = [self._guid_to_keysound[guid].track_guid for guid in self._selected_keysounds]
        if all(v == values[0] for v in values):
            return values[0]
        return None

    def set_selected_keysounds_track(self, track_guid):
        self.refresh_guid_mappings()

        removed_keysounds = []
        for group in self._track_groups:
            for track in group.tracks:
                to_keep = []
                for keysound in track.keysounds:
                    if keysound.guid in self._selected_keysounds:
                        removed_keysounds.append(keysound)
                    else:
                        to_keep.append(keysound)
                track.keysounds = to_keep

        for keysound in removed_keysounds:
            keysound.track_guid = track_guid

        self._guid_to_track[track_guid].keysounds += removed_keysounds
        self._guid_to_track[track_guid].sort_keysounds()

    def compute_clusters(self, all_groups=False):
        if all_groups:
            groups = self._track_groups
        else:
            groups = self._get_selected_groups()

        for group in groups:
            self._compute_clusters_for_group(group, group.properties)

    def _compute_clusters_for_group(self, group, properties):
        keysounds = [k for track in group.tracks for k in track.keysounds]
        audio_datas = {keysound.guid: keysound.get_audio_data(substitute=False) for keysound in keysounds}
        audio_data_by_id = {ad.id: ad for ad in audio_datas.values()}
        audio_data_ids_sorted = sorted(audio_data_by_id.keys()) # already guaranteed to have no duplicates

        self.log('Computing feature vectors...')
        feature_vectors = [audio_data_by_id[i].get_unweighted_feature_vector(properties['mfcc_size']) for i in audio_data_ids_sorted]
        X = keysound_clustering.compute_combined_features(feature_vectors, weights={
            # "mfcc": 0.40,      # Timbre (Identity)
            # "delta": 0.20,     # Temporal Dynamics
            # "loudness": 0.20,  # Volume/Energy
            # "spectral": 0.10,  # Brightness
            # "pitch": 0.10,     # Intonation
            "mfcc": properties["weight_mfcc"],
            "delta": properties["weight_temporal"],
            "loudness": properties["weight_volume"],
            "spectral": properties["weight_brightness"],
            "pitch": properties["weight_pitch"],
        })
        #scaler = StandardScaler()  TODO: REMOVE
        #X = scaler.fit_transform(feature_vectors)
        #X[:,-2:] *= properties['volume_weight']

        self.log('Computing clusters...')
        clusters, size = keysound_clustering.compute_clusters(X, properties['threshold'], properties['metric'], properties['algorithm'])

        audio_data_id_to_index = {adid:index for index, adid in enumerate(audio_data_ids_sorted)}
        self._last_clustering_distance_query = keysound_clustering.DistanceQuery(X, properties['metric'])
        for keysound in keysounds:
            # keysound -> keysound.guid -> audio_data.id -> arr_index -> cluster_arr_index -> cluster's audio_data.id
            audio_data_id = audio_datas[keysound.guid].id
            arr_index = audio_data_id_to_index[audio_data_id]
            cluster_arr_index = clusters[arr_index]
            cluster_audio_data_id = audio_data_ids_sorted[cluster_arr_index]
            keysound.properties['substitute_audio_data_id'] = cluster_audio_data_id

            #if arr_index == cluster_arr_index:  TODO: REMOVE
                #audio_distance = 0.0
            #else:
                #audio_distance = self.distance_query.distance(arr_index, cluster_arr_index)
            #keysound.set_last_substitution_audio_distance(audio_distance)
        self._last_clustering_distance_query.setup_keysound_distance_queries(
            #{keysound_guid: audio_data_id_to_index[audio_datas[keysound_guid].id] for keysound_guid in audio_datas.keys()},  TODO: REMOVE
            audio_data_id_to_index,
            clusters
        )
        self.log('Clustering complete!')

    def compute_counters(self):
        self.refresh_guid_mappings()
        all_keysounds = self._get_keysounds()
        selected_groups = self._get_selected_groups()
        selected_tracks = self._get_selected_tracks()
        keysounds_of_selected_groups = [ks for gp in selected_groups for tk in gp.tracks for ks in tk.keysounds]
        keysounds_of_selected_tracks = [ks for tk in selected_tracks for ks in tk.keysounds]

        count_vars = {}
        count_vars['num_selected_keysounds'] = len(self._selected_keysounds)
        count_vars['num_selected_tracks'] = len(self._selected_tracks)
        count_vars['num_selected_groups'] = len(selected_groups)

        count_vars['base_unique_keysounds'] = len(set(ks.get_audio_data(substitute=False).id for ks in all_keysounds))
        count_vars['optimized_unique_keysounds'] = len(set(ks.get_audio_data(substitute=True).id for ks in all_keysounds))
        count_vars['base_tracks_unique_keysounds'] = len(set(ks.get_audio_data(substitute=False).id for ks in keysounds_of_selected_tracks))
        count_vars['optimized_tracks_unique_keysounds'] = len(set(ks.get_audio_data(substitute=True).id for ks in keysounds_of_selected_tracks))
        count_vars['base_groups_unique_keysounds'] = len(set(ks.get_audio_data(substitute=False).id for ks in keysounds_of_selected_groups))
        count_vars['optimized_groups_unique_keysounds'] = len(set(ks.get_audio_data(substitute=True).id for ks in keysounds_of_selected_groups))

        count_vars['audio_distance'] = self._get_current_audio_distance()

        return count_vars

    def _get_current_audio_distance(self) -> str:
        if self._last_clustering_distance_query is None:
            return ''

        def get_audio_data_id(guid, substitute=False):
            return self.get_keysound(guid).get_audio_data(substitute=substitute).id

        selected_keysounds = self.get_selected_keysounds()
        if len(selected_keysounds) == 1:
            (ks,) = selected_keysounds
            adid1 = get_audio_data_id(ks.guid, substitute=False)

            # TODO: HACL
            if False:
                import librosa
                import numpy as np
                d,sr = ks.get_audio_data().get_data()

                pitch, _, _ = librosa.pyin(d.T, fmin=librosa.note_to_hz('C2'),fmax=librosa.note_to_hz('C7'), 
                                    sr=sr, hop_length=512,resolution=0.5,)
                percentage_nan = np.isnan(pitch).mean() * 100
                return 'FLAT: %.1f' % percentage_nan
                #return 'FLAT: %.5f' % np.mean(librosa.feature.spectral_flatness(y=d.T))
            

            adid2 = get_audio_data_id(ks.guid, substitute=True)
            dist = self._last_clustering_distance_query.distance_audio_datas(adid1, adid2)
            return f"Dist ({adid1}->{adid2}): {dist:.3f}"
        elif len(selected_keysounds) == 2:
            (ks1, ks2) = selected_keysounds
            adid1, adid2 = map(get_audio_data_id, (ks1.guid, ks2.guid))
            dist = self._last_clustering_distance_query.distance_audio_datas(adid1, adid2)
            return f"Dist ({adid1}->{adid2}): {dist:.3f}"
        else:
            return ''