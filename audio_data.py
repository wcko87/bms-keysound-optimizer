from abc import ABC, abstractmethod
from utils import *
import os
import soundfile as sf
import keysound_clustering
import shutil

## Audio sources:
# 1. BMS metadata + keysound_id -> audio file
# 2. audio path (stem) + start/end indices -> data chopped

class AudioDataLoader(object):
    def __init__(self):
        self._next_audio_data_id = 0
        self._bms_cache = {}
        self._audio_path_cache = {}
        self._audio_file_data_cache = {}
        self._audio_data_by_id = {}

    def get_audio_data(self, audio_data_id):
        return self._audio_data_by_id.get(audio_data_id)

    def load_audio_from_file(self, file_name):
        data_sr = self._audio_file_data_cache.get(file_name)
        if data_sr is not None: return data_sr
        data, sample_rate = sf.read(file_name)
        self._audio_file_data_cache[file_name] = (data, sample_rate)
        return data, sample_rate

    def from_bms(self, bms_path, bms, bms_hash, keysound_id):
        key = (bms_hash, keysound_id)
        if key in self._bms_cache:
            return self._bms_cache[key]
        audio_data = BMSAudioData(self, self._next_audio_data_id, bms_hash, bms_path, bms, keysound_id)
        self._next_audio_data_id += 1
        self._bms_cache[key] = audio_data
        self._audio_data_by_id[audio_data.id] = audio_data
        return audio_data

    def from_audio_path(self, file_path, start_index, end_index, filters=None):
        key = (file_path, start_index, end_index)
        if key in self._audio_path_cache:
            return self._audio_path_cache[key]
        audio_data = StemAudioData(self, self._next_audio_data_id, file_path, start_index, end_index, filters)
        self._next_audio_data_id += 1
        self._audio_path_cache[key] = audio_data
        self._audio_data_by_id[audio_data.id] = audio_data
        return audio_data

class IAudioData(ABC):
    def __init__(self, audio_data_id):
        self.id = audio_data_id
        self.load_already_attempted = False
        self.data = None
        self.sample_rate = None
        self.feature_vector = None

        self._last_mfcc_size = None

    @abstractmethod
    def get_data(self):
        pass

    @abstractmethod
    def export_to_file(self, output_dir, extensionless_filename):
        pass

    @abstractmethod
    def suggest_file_name(self):
        pass

    def get_already_computed_feature_vector(self):
        if self.feature_vector is None: return None
        return self.feature_vector

    def get_unweighted_feature_vector(self, mfcc_size=13):
        if self.feature_vector is None or self._last_mfcc_size != mfcc_size:
            self.get_data()
            self.feature_vector = keysound_clustering.compute_feature_vectors(
                self.data, self.sample_rate, mfcc_size=mfcc_size,
            )
            #self.feature_vector = keysound_distances.compute_feature_vectors(
                #[(self.id, self.data, self.sample_rate)],
                #verbose=False, mfcc_size=mfcc_size, rms_weight=1.0, normalize=False)[0]
            self._last_mfcc_size = mfcc_size
        return self.feature_vector

    def get_duration_ms(self):
        self.get_data()
        if self.data is None: return None
        return self.data.shape[0]/self.sample_rate*1000

    def __eq__(self, other):
        if not isinstance(other, IAudioData): return False
        return self.id == other.id

    def __hash__(self):
        return self.id

class BMSAudioData(IAudioData):
    def __init__(self, audio_data_loader, audio_data_id, bms_hash, bms_path, bms, keysound_id):
        super().__init__(audio_data_id)
        self.audio_data_loader = audio_data_loader
        self.bms_hash = bms_hash
        self.bms_path = bms_path
        self.bms = bms
        self.keysound_id = keysound_id

    def resolve_keysound_path(self, directory, keysound_filename):
        keysound_path = os.path.join(directory, keysound_filename)
        if os.path.isfile(keysound_path): return keysound_path
        root, ext = os.path.splitext(keysound_path)
        keysound_path = root + '.wav'
        if os.path.isfile(keysound_path): return keysound_path
        root, ext = os.path.splitext(keysound_path)
        keysound_path = root + '.ogg'
        if os.path.isfile(keysound_path): return keysound_path
        return None
    
    def get_data(self):
        if self.data is not None:
            return self.data, self.sample_rate
        if self.load_already_attempted: # TODO: figure out a system for retrying instead of giving up forever after one failure
            return None, None
        self.load_already_attempted = True

        keysound_filename = self.bms.metadata.keysounds.get(self.keysound_id)
        if keysound_filename is None: return None, None
        directory = os.path.dirname(self.bms_path)
        self.keysound_path = self.resolve_keysound_path(directory, keysound_filename)
        if self.keysound_path is None: return None, None
        #print(f"LOAD KEYSOUND AUDIO: {self.id}, {keysound_filename}")

        data, sample_rate = self.audio_data_loader.load_audio_from_file(self.keysound_path)
        if data is None: return None, None

        self.data = data
        self.sample_rate = sample_rate
        return self.data, self.sample_rate

    def export_to_file(self, output_dir, extensionless_filename):
        # copy file instead of rewriting
        self.get_data()
        filename, extension = os.path.splitext(self.keysound_path)
        new_file_path = os.path.join(output_dir, extensionless_filename + extension)
        shutil.copy(self.keysound_path, new_file_path)

    def suggest_file_name(self):
        return self.bms.metadata.keysounds.get(self.keysound_id, None)


class StemAudioData(IAudioData):
    def __init__(self, audio_data_loader, audio_data_id, audio_path, start_index, end_index, filters=None):
        super().__init__(audio_data_id)
        self.audio_data_loader = audio_data_loader
        self.audio_path = audio_path
        self.start_index = start_index
        self.end_index = end_index

    def get_data(self):
        if self.data is not None:
            return self.data, self.sample_rate
        if self.load_already_attempted:
            return None, None
        self.load_already_attempted = True

        data, sample_rate = self.audio_data_loader.load_audio_from_file(audio_path)
        if data is None: return None, None

        self.data = data[start_index:end_index]
        self.sample_rate = sample_rate
        return self.data, self.sample_rate

    def export_to_file(self, output_dir, extensionless_filename):
        # TODO write from data, apply filters if active
        # look at keysound_export.py and modify that to fit
        self.get_data()
        new_file_path = os.path.join(output_dir, extensionless_filename + '.ogg')
        sf.write(new_file_path, self.data, self.samplerate, format='OGG', subtype='VORBIS')

    def suggest_file_name(self):
        return os.path.basename(self.audio_path)
