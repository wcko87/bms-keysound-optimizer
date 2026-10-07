import librosa
import numpy as np
from fastdtw import fastdtw
from scipy.spatial.distance import euclidean
from sklearn.preprocessing import StandardScaler
from sklearn.neighbors import BallTree
from scipy.spatial.distance import cdist

def compute_stat_summary(feature, rms):
    # input: feature of shape (num_channels, num_features, num_windows)
    # where the third axis is chronological with some window size like 512

    # we use rms weighting so that silent sections have lower weights.
    # this is also so that the trailing silence at the end of keysounds isn't compared (hopefully?)

    weights = rms.copy()
    weight_sum = np.sum(weights, axis=2, keepdims=True)
    weight_sum = np.where(weight_sum == 0, 1.0, weight_sum) # to avoid divide by zero oddities
    norm_weights = weights / weight_sum 

    # trim off silent tails (silent tails heavily affect especially the mean and skew)
    cum_weight = np.cumsum(norm_weights)
    cutoff_index = np.where(cum_weight >= 0.95)[0][0]
    norm_weights = norm_weights[:cutoff_index + 1]
    feature = feature[:cutoff_index + 1]

    feature *= norm_weights
    
    # first moment (mean)
    mean_w = np.sum(feature, axis=2, keepdims=True)
    
    delta = feature - mean_w
    
    # second moment (variance, std)
    var_w = np.sum((delta ** 2), axis=2, keepdims=True)
    std_w = np.sqrt(var_w)
    safe_std_w = np.where(std_w == 0, 1e-10, std_w)
    
    # third moment (skew)
    skew_w = np.sum((delta ** 3), axis=2, keepdims=True) / (safe_std_w ** 2) # **2 instead of **3 so that it has the same units as mean
    
    # fourth moment (kurtosis)
    kurt_w = (np.sum((delta ** 4), axis=2, keepdims=True) / (safe_std_w ** 3)) # **3 instead of **4 so that it has the same units as mean
    
    return np.concatenate([
        np.squeeze(mean_w, axis=2),
        np.squeeze(std_w, axis=2),
        np.squeeze(skew_w, axis=2),
        np.squeeze(kurt_w, axis=2),
    ], axis=1)



def compute_feature_vectors(data, sample_rate, mfcc_size=13, n_fft=2048, hop_length=512):
    y, sr = data.T, sample_rate
    if y.ndim == 1:
        y = np.expand_dims(y, axis=0)

    min_samples = n_fft + 8*hop_length
    if y.shape[-1] < min_samples:
        y = librosa.util.fix_length(y, size=min_samples, axis=-1)

    # 1. MFCC for timbre
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=mfcc_size, n_fft=n_fft, hop_length=hop_length)
    #print(f'mfcc: {mfcc.shape}')

    # 2. delta of MFCC for dynamics
    delta = librosa.feature.delta(mfcc)
    #print(f'delta: {delta.shape}')
    
    # 3. RMS for loudness
    rms = librosa.feature.rms(y=y, frame_length=n_fft, hop_length=hop_length)
    #print(f'rms: {rms.shape}')
    loudness = librosa.amplitude_to_db(rms, ref=np.max)
    #print(f'loudness: {loudness.shape}')
    
    # 4. brightness and flux
    centroid = librosa.feature.spectral_centroid(y=y, sr=sr, n_fft=n_fft, hop_length=hop_length)
    #print(f'centroid: {centroid.shape}')
    flux = librosa.onset.onset_strength_multi(y=y, sr=sr, hop_length=hop_length)
    #n_frames = mfcc.shape[2]
    #flux = flux[:,:,:n_frames]
    #if flux.shape[-1] < n_frames:
        #pad_width = n_frames - flux.shape[-1]
        #flux = np.pad(flux, ((0, 0), (0, 0), (pad_width, 0)), mode='edge')
    #print(f'flux: {flux.shape}')
    
    # 5. pitch
    #pitch, _, _ = librosa.pyin(y, fmin=librosa.note_to_hz('C2'), 
                            #fmax=librosa.note_to_hz('C7'), 
                            #sr=sr, hop_length=hop_length,
                            #resolution=0.3,
                            #)
    pitch = librosa.yin(y, fmin=librosa.note_to_hz('C2'), 
                            fmax=librosa.note_to_hz('C7'), 
                            sr=sr, hop_length=hop_length,
                            )
    pitch = np.nan_to_num(pitch) # NaN values become 0

    if False:
        pitch_nancheck, _, _ = librosa.pyin(y, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('C7'), 
                            sr=sr, hop_length=hop_length, resolution=0.5)
        pitch[np.isnan(pitch_nancheck)] = 0
    pitch = np.expand_dims(pitch, axis=1)

    #print(f'pitch: {pitch.shape}')

    features = {
        "mfcc": mfcc, 
        "delta": delta, 
        "loudness": loudness,
        "spectral": np.concatenate([centroid, flux], axis=1),
        "pitch": pitch
    }
    features = {k: compute_stat_summary(v, rms) for k, v in features.items()}
    return features

def compute_combined_features(featuress, weights):
    keys = sorted(featuress[0].keys())

    weighted_features = []
    for key in keys:
        feature_vectors = [features[key].flatten() for features in featuress]
        scaler = StandardScaler()
        X_key = scaler.fit_transform(feature_vectors)

        X_key *= 100/(len(keys)*X_key.shape[1])
        X_key *= weights[key]
        weighted_features.append(X_key)
        #print(key, X_key.shape)
        #print(X_key.sum(axis=1))

    return np.concatenate(weighted_features, axis=1)


class DistanceQuery:
    def __init__(self, X, metric):
        self.X = X
        self.kwargs = {}

        # convert metric name because cdist doesn't accept manhattan for some reason
        if metric == 'manhattan':
            self.metric = 'cityblock'
        else:
            self.metric = metric

        # prepare additional arguments for the metrics that need it
        if metric == 'seuclidean':
            variance = np.var(X, axis=0, ddof=1)
            self.kwargs['V'] = variance
        if self.metric == 'mahalanobis':
            cov = np.cov(X.T)
            self.kwargs['VI'] = np.linalg.pinv(cov)

    def setup_keysound_distance_queries(self, audio_data_id_to_index, clusters):
        self.audio_data_id_to_index = audio_data_id_to_index
        self.clusters = clusters

    def distance_audio_datas(self, audio_data_id_1, audio_data_id_2):
        return self._distance(
            i=self.audio_data_id_to_index[audio_data_id_1],
            j=self.audio_data_id_to_index[audio_data_id_2],
        )

    def _distance(self, i, j):
        v1 = self.X[i].reshape(1, -1)
        v2 = self.X[j].reshape(1, -1)
        # cdist returns a 2D array of shapes (1, 1), extract the scalar element
        return float(cdist(v1, v2, metric=self.metric, **self.kwargs)[0, 0])

def create_balltree(X, metric):
    if metric == 'seuclidean':
        variance = np.var(X, axis=0, ddof=1) 
        return BallTree(X, metric=metric, V=variance)
    elif metric == 'mahalanobis':
        cov = np.cov(X.T)
        VI = np.linalg.pinv(cov) #pseudo-inverse
        return BallTree(X, metric=metric, VI=VI)
    else:
        return BallTree(X, metric=metric)

def compute_clusters(X, eps, metric, algorithm):
    if algorithm == 'weighted_dominating_set':
        domset = np.array(fast_geometric_dominating_set_w(X, eps, metric))

    tree = create_balltree(X[domset], metric=metric)
    
    distances, indices = tree.query(X, k=1)
    clusters = domset[indices.flatten()]

    return clusters, len(domset)

def fast_geometric_dominating_set_w(X, eps, metric='euclidean'):
    tree = create_balltree(X, metric=metric)
    neighbors = tree.query_radius(X, r=eps)
    covered = np.zeros(len(X), dtype=bool)
    dominating_set = []

    weights = [np.exp(-np.linalg.norm(X[idx] - X[i], 2, axis=1)) for i, idx in enumerate(neighbors)]
    while not np.all(covered):
        #uncovered_counts = [np.sum(~covered[idx]) for idx in neighbors]
        uncovered_counts_w = [
            np.sum(~covered[idx]*weights[i])
            for i,idx in enumerate(neighbors)
        ]
        best_node = np.argmax(uncovered_counts_w)
        #print(best_node, uncovered_counts[best_node],uncovered_counts_w[best_node]) 
        dominating_set.append(best_node)
        covered[neighbors[best_node]] = True
    return dominating_set





def main():
    import soundfile as sf
    PATH1 = r'./notes/test_bms/conjunctiva_ogg/synth_sabi_1_1.ogg'
    PATH2 = r'./notes/test_bms/conjunctiva_ogg/synth_sabi_2_1.ogg'
    PATH3 = r'./notes/test_bms/conjunctiva_ogg/synth_sabi_1_2.ogg'
    PATH4 = r'./notes/test_bms/conjunctiva_ogg/synth_sabi_2_2.ogg'
    data, sample_rate = sf.read(PATH1)
    f1 = compute_feature_vectors(data, sample_rate)
    data, sample_rate = sf.read(PATH2)
    f2 = compute_feature_vectors(data, sample_rate)
    data, sample_rate = sf.read(PATH3)
    f3 = compute_feature_vectors(data, sample_rate)
    data, sample_rate = sf.read(PATH4)
    f4 = compute_feature_vectors(data, sample_rate)

    np.set_printoptions(suppress=True)
    np.set_printoptions(precision=2)
    if False:
        for k,v in f2.items():
            print(k, v.shape)
            print(v)
        quit()

    feature_vectors = [f1, f2, f3, f4]
    X = compute_combined_features(feature_vectors, weights={
        "mfcc": 0.40,      # Timbre (Identity)
        "delta": 0.20,     # Temporal Dynamics
        "loudness": 0.20,  # Volume/Energy
        "spectral": 0.10,  # Brightness
        "pitch": 0.10,     # Intonation
    })
    print(X.shape)
    for i in range(X.shape[0]):
        for j in range(i+1, X.shape[0]):
            print(np.linalg.norm(X[i] - X[j]))

    clusters, size = compute_clusters(X, 2.0, 'euclidean', 'weighted_dominating_set')

    

if __name__ == '__main__':
    main()