import numpy as np
import argparse

from common_utils.hdf_utils import load_subject_fmri
from common_utils.stimulus_utils import load_grids_for_stories, load_generic_trfiles
from ridge_utils.dsutils import make_word_ds, make_phoneme_ds, make_semantic_model
from ridge_utils.ridge import bootstrap_ridge
from common_utils.SemanticModel import SemanticModel
import os
from common_utils.npp import zscore
from common_utils.util import make_delayed

trim = 5
data_dir = 'data'


def predict_brain_activity(subjectNum, featurename, modality, dirname, layer):
    stimul_features = np.load(featurename, allow_pickle=True)
    print(stimul_features.item().keys())
    training_story_names = ['alternateithicatom', 'avatar', 'howtodraw', 'legacy',
                            'life', 'myfirstdaywiththeyankees', 'naked',
                            'odetostepfather', 'souls', 'undertheinfluence']
    # Pstories are the test (or Prediction) stories (well, story), which we will use to test our models
    prediction_story_names = ['wheretheressmoke']
    all_story_names = training_story_names + prediction_story_names
    grids = load_grids_for_stories(all_story_names)
    # Load TRfiles
    trfiles = load_generic_trfiles(all_story_names, root="stimuli/trfiles")
    # Make word and phoneme datasequences
    wordseqs = make_word_ds(grids, trfiles)  # dictionary of {storyname : word DataSequence}
    eng1000 = SemanticModel.load(os.path.join(data_dir, "english1000sm.hf5"))
    semanticseqs = dict()  # dictionary to hold projected stimuli {story name : projected DataSequence}
    for story in all_story_names:
        semanticseqs[story] = make_semantic_model(wordseqs[story], [eng1000], [985])
    story_filenames = ['alternateithicatom', 'avatar', 'howtodraw', 'legacy',
                       'life', 'myfirstdaywiththeyankees', 'naked',
                       'odetostepfather', 'souls', 'undertheinfluence', 'wheretheressmoke']
    semanticseqs = dict()
    for i in np.arange(len(all_story_names)):
        semanticseqs[all_story_names[i]] = []
        temp = make_semantic_model(wordseqs[all_story_names[i]], [eng1000], [985])
        temp.data = np.nan_to_num(stimul_features.item()[story_filenames[i]][layer])
        semanticseqs[all_story_names[i]] = temp
    # Downsample stimuli
    interptype = "lanczos"  # filter type
    window = 3  # number of lobes in Lanczos filter
    downsampled_semanticseqs = dict()  # dictionary to hold downsampled stimuli
    for story in all_story_names:
        downsampled_semanticseqs[story] = semanticseqs[story].chunksums(interptype, window=window)
    trim = 5

    training_stim = np.vstack(
        [zscore(downsampled_semanticseqs[story][5 + trim:-trim]) for story in training_story_names])
    predicion_stim = np.vstack(
        [zscore(downsampled_semanticseqs[story][5 + trim:-trim]) for story in prediction_story_names])
    story_lengths = [len(downsampled_semanticseqs[story][0][5 + trim:-trim]) for story in training_story_names]
    print(story_lengths)
    #### save downsampled stimuli
    bert_downsampled_data = {}
    for eachstory in list(downsampled_semanticseqs.keys()):
        bert_downsampled_data[eachstory] = np.array(downsampled_semanticseqs[eachstory].data)
    np.save('bert_downsampled_data', bert_downsampled_data)
    #########
    # Delay stimuli
    numer_of_delays = 6
    delays = range(1, numer_of_delays + 1)

    print("FIR model delays: ", delays)
    print(np.array(training_stim).shape)

    delayed_Rstim = make_delayed(np.array(training_stim), delays)
    delayed_Pstim = make_delayed(np.array(predicion_stim), delays)

    print("delRstim shape: ", delayed_Rstim.shape)
    print("delPstim shape: ", delayed_Pstim.shape)
    subject = f'0{subjectNum}'
    main_dir = os.path.join(dirname, modality, subject)
    if not os.path.exists(main_dir):
        os.makedirs(main_dir)
    # Run regression
    nboots = 1  # Number of cross-validation runs.
    chunklen = 40  #
    nchunks = 20
    zRresp, zPresp = load_subject_fmri(data_dir, subject, modality)
    alphas = np.logspace(1, 3,
                         10)  # Equally log-spaced alphas between 10 and 1000. The third number is the number of alphas to test.
    wt, corr, alphas, bscorrs, valinds = bootstrap_ridge(np.nan_to_num(delayed_Rstim), zRresp,
                                                         np.nan_to_num(delayed_Pstim), zPresp,
                                                         alphas, nboots, chunklen, nchunks,
                                                         singcutoff=1e-10, single_alpha=True)
    pred = np.dot(np.nan_to_num(delayed_Pstim), wt)
    voxcorrs = np.zeros((zPresp.shape[1],))  # create zero-filled array to hold correlations
    for vi in range(zPresp.shape[1]):
        voxcorrs[vi] = np.corrcoef(zPresp[:, vi], pred[:, vi])[0, 1]

    np.save(os.path.join(str(main_dir), "layer_" + str(layer)), voxcorrs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Predict brain activity")
    parser.add_argument("subjectNum", help="Choose subject", type=int)
    parser.add_argument("featurename", help="Choose feature", type=str)
    parser.add_argument("modality", help="Choose modality", type=str)
    parser.add_argument("dirname", help="Choose Directory", type=str)
    parser.add_argument("layer",
                        help="Internal layer of natural language model to use for semantic representation of words",
                        type=int)
    args = parser.parse_args()
    print(args)

    predict_brain_activity(args.subjectNum, args.featurename, args.modality, args.dirname, args.layer)
