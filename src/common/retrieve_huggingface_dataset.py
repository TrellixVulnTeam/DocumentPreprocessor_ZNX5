from clearml import Task, StorageManager, Logger, Dataset

import pandas as pd 
import numpy as np


PROJECT_NAME = "incubation c4"
TASK_NAME = "dataset_store_c4_dataset"
DATASET_PROJECT = "datasets/c4"
DATASET_NAME = "c4_raw_clean"

task = Task.init(project_name=PROJECT_NAME, task_name=TASK_NAME,output_uri='s3://experiment-logging')
task.set_base_docker(
    docker_image="nvidia/cuda:11.4.0-cudnn8-devel-ubuntu20.04",
)

args = {
    "clean_dataset_name": "c4",
    "clean_dataset_variant_name": "en",
    "clean_dataset_split": "train",
    "unclean_dataset_name": "c4",
    "unclean_dataset_variant_name": "en.noclean",
    "unclean_dataset_split": "train",
}

task.connect(args)
task.execute_remotely(queue_name='compute')

print(args)

clean_dataset_name = args["clean_dataset_name"]
clean_dataset_variant_name = args["clean_dataset_variant_name"]
clean_dataset_split = args["clean_dataset_split"]

unclean_dataset_name = args["unclean_dataset_name"]
unclean_dataset_variant_name = args["unclean_dataset_variant_name"]
unclean_dataset_split = args["unclean_dataset_split"]


################## dataset_store_c4_datasets #################
from datasets import load_dataset, load_from_disk, concatenate_datasets

cleaned_dataset = load_dataset(
    path='allenai/c4',data_files='en/c4-train.0000[0-1]-of-01024.json.gz',split=clean_dataset_split
)


uncleaned_dataset = load_dataset(
    path='allenai/c4',data_files='en.noclean/c4-train.0000[0-1]-of-07168.json.gz',split=unclean_dataset_split
)

print("Number of samples in {} dataset".format(args['clean_dataset_name']), cleaned_dataset.num_rows)
print("Number of samples in {} dataset".format(args['unclean_dataset_name']), uncleaned_dataset.num_rows)


def dataset_to_shard(dataset, shard_path="/tmp/dataset", num_shards=8):
    for index in range(num_shards):
        dataset.shard(num_shards=num_shards, index=index).save_to_disk(
            "{}/shard_{}".format(shard_path, index)
        )
    return shard_path


def shard_to_dataset(shard_path="/tmp/dataset", num_shards=8):
    dataset = concatenate_datasets(
        [load_from_disk("{}/shard_{}".format(shard_path, i)) for i in range(num_shards)]
    )
    return dataset

def create_dataset(dataset_project, dataset_name):
    parent_dataset = _get_last_child_dataset(dataset_project, dataset_name)
    if parent_dataset:
        print("create child")
        if not parent_dataset.is_final():
            parent_dataset.finalize()
        child_dataset = Dataset.create(
            dataset_name, dataset_project, parent_datasets=[parent_dataset]
        )
        return child_dataset
    else:
        print("create parent")
        dataset = Dataset.create(dataset_name, dataset_project)
        return dataset


def _get_last_child_dataset(dataset_project, dataset_name):
    datasets_dict = Dataset.list_datasets(
        dataset_project=dataset_project, partial_name=dataset_name, only_completed=False
    )
    if datasets_dict:
        datasets_dict_latest = datasets_dict[-1]
        return Dataset.get(dataset_id=datasets_dict_latest["id"])


## shard dataset and save
cleaned_shard_path = dataset_to_shard(cleaned_dataset,shard_path="/tmp/cleaned_dataset")
uncleaned_shard_path = dataset_to_shard(uncleaned_dataset,shard_path="/tmp/uncleaned_dataset")

## load dataset from shards
clean_dataset = shard_to_dataset(cleaned_shard_path, num_shards=8)
unclean_dataset = shard_to_dataset(uncleaned_shard_path, num_shards=8)

clean_df = clean_dataset.to_pandas()
print(clean_df.info())
unclean_df = unclean_dataset.to_pandas()
print(unclean_df.info())


result = pd.merge(clean_df,unclean_df,how="inner",left_on='url',right_on='url',suffixes=("", "_y"))
result = result.drop(['timestamp_y'], axis = 1)
result.rename(columns={'text': 'clean', 'text_y': 'raw'}, inplace=True)
result['doc_id'] = result.index
print(result.info())

print(clean_dataset.features)
# print(clean_dataset.unique('url'))

train, validate, test = np.split(result.sample(frac=1, random_state=42), [int(.6*len(result)), int(.8*len(result))])

dataset = create_dataset(
    dataset_project=DATASET_PROJECT,
    dataset_name=DATASET_NAME,
)

# dataset = Dataset.create(
#     dataset_project='datasets/c4', dataset_name="c4_raw_clean"
# )

train.to_parquet("train.parquet", engine='fastparquet')
validate.to_parquet("validate.parquet", engine='fastparquet')
test.to_parquet("test.parquet", engine='fastparquet')
# df.to_csv("dataset_dataframe.csv.gz", compression="gzip")
dataset.add_files("train.parquet")
dataset.add_files("validate.parquet")
dataset.add_files("test.parquet")
dataset.upload()
dataset.finalize()
