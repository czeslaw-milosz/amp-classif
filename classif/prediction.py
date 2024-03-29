import io
import os
import random
import string
import time
from typing import Dict

import Bio
import pandas as pd
import requests
import requests_toolbelt as toolbelt
from keras.models import load_model
from keras.preprocessing import sequence

from classif.config import Config
from classif import utils


CONFIG = Config()


def predict_ampscanner(input_path: str, output_dir: str, verbose: bool = True) -> None:
    basename = os.path.splitext(os.path.basename(input_path))[0]
    outfile = os.path.join(output_dir, f"{basename}_pred_ampscannerv2.csv")
    result = utils.clean_ampscanner_preds(get_ampscanner_predictions(input_path, verbose))
    result.to_csv(outfile, index=False)


def predict_dbaasp(input_path: str, output_dir: str, strain: str = "Escherichia coli ATCC 25922", verbose: bool = True) -> None:
    payload = list(Bio.SeqIO.parse(input_path, "fasta"))
    if not strain:
        names = [item.id for item in payload]  # backup of actual sequence ids bc of a bug in dbaasp server-side code
        for i, item in enumerate(payload):
            item.id = str(i)
    payload = (item.format("fasta") for item in payload)
    result = (get_dbaasp_predictions("".join(chunk), strain, verbose)
              for chunk in utils.split_into_chunks(payload, chunk_size=Config.DBAASP_CHUNK_SIZE))
    result = pd.concat((partial for partial in result if partial is not None), axis="rows", ignore_index=True)
    basename = os.path.splitext(os.path.basename(input_path))[0]
    strain = strain.replace(' ', '_') if strain else "general"
    outfile = os.path.join(output_dir, f"{basename}_pred_dbaasp_{strain}.csv")
    if strain == "general":
        result["id"] = names
    if result is not None:
        result.to_csv(outfile, index=False)
    if verbose:
        print(f"saved predictions to {outfile}")


def predict_dbaasp_genome(input_path: str, output_dir: str = "",
                          strain: str = "", genbank_id: int = 2137, verbose: bool = True) -> None:
    payload = (item.format("fasta") for item in Bio.SeqIO.parse(input_path, "fasta"))
    result = (get_dbaasp_genome_predictions("".join(chunk), strain, genbank_id, verbose=verbose)
              for chunk in sorted(utils.split_into_chunks(payload, chunk_size=Config.DBAASP_GENOME_CHUNK_SIZE)))
    result = pd.concat((partial for partial in result if partial is not None), axis="rows", ignore_index=True)
    outfile = os.path.basename(input_path).replace(".fasta", f"_pred_dbaasp_genome_{strain.replace(' ', '_')}.csv")
    outfile = os.path.join(output_dir, outfile)
    if result is not None:
        result.to_csv(outfile, index=False)
    if verbose:
        print(f"saved predictions to {outfile}")


def predict_campr3(input_path: str, output_dir: str = "", verbose: bool = True) -> None:
    payload = "".join(item.format("fasta") for item in Bio.SeqIO.parse(input_path, "fasta"))
    result = get_campr3_predictions(payload, verbose)
    for algo, df in result.items():
        outfile = os.path.basename(input_path).replace(".fasta", f"_pred_{algo}.csv")
        outfile = os.path.join(output_dir, outfile)
        if df is not None:
            df.to_csv(outfile, index=False)
        if verbose:
            print(f"saved predictions to {outfile}")


def predict_stm(input_path: str, output_dir: str = "", verbose: bool = True) -> None:
    payload = "".join(item.format("fasta") for item in Bio.SeqIO.parse(input_path, "fasta"))
    result = get_stm_predictions(payload, verbose)
    outfile = os.path.basename(input_path).replace(".fasta", f"_pred_stm.csv")
    outfile = os.path.join(output_dir, outfile)
    if result is not None:
        result.to_csv(outfile, index=False)
    if verbose:
        print(f"saved predictions to {outfile}")


def get_ampscanner_predictions(input_path: str, verbose: bool = True) -> pd.DataFrame:
    os.environ["TF_CPP_MIN_LOG_LEVEL"] = "2"
    if verbose:
        print("Encoding sequences...")
    X_test, warn, ids, seqs = utils.setup_ampscanner(input_path)
    X_test = sequence.pad_sequences(X_test, maxlen=Config.AMPSCANNER_MAX_LENGTH)

    if verbose:
        print("Loading model and weights from file: " + Config.AMPSCANNER_MODEL_PATH)
    model = load_model(Config.AMPSCANNER_MODEL_PATH)

    print("Making predictions...")
    preds = model.predict(X_test)
    rows = [
        [ids[i], f"AMP{warn[i]}" if pred[0] >= Config.AMPSCANNER_THRESHOLD else f"Non-AMP{warn[i]}", round(pred[0], 4), seqs[i]]
        for i, pred in enumerate(preds)
    ]
    if verbose:
        print("JOB FINISHED: " + time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()))
    return pd.DataFrame(rows, columns=["SeqID", "Prediction_Class", "Prediction_Probability", "Sequence"])


def get_campr3_predictions(payload: str, verbose: bool = True) -> Dict[str, pd.DataFrame]:
    result = {}
    for algo in CONFIG.CAMPR3_AVAILABLE_MODELS:
        if verbose:
            print(f"Sending prediction request to CAMPR3 {algo}...")
        fields = {
            "S1": payload,
            "userfile": ("", b'', "application/octet-stream"),
            "algo[]": (None, algo),
            "B1": "Submit",
        }
        boundary = "----WebKitFormBoundary" + "".join(random.sample(string.ascii_letters + string.digits, 16))
        enc = toolbelt.MultipartEncoder(fields=fields, boundary=boundary)
        response = requests.post(Config.CAMPR3_URL, data=enc, headers={'Content-Type': enc.content_type})
        status = response.status_code
        if verbose:
            print(f"request status: {status}")
        df = utils.clean_campr3_preds(pd.read_html(response.content)[3]) if status == 200 else None
        result[f"campr3_{algo}"] = df
    return result


def get_dbaasp_predictions(payload: str, strain: str = "Escherichia coli ATCC 25922", verbose: bool = True) -> pd.DataFrame:
    if verbose:
        print("Sending prediction request to DBAASP...")
    request_data = {
            "strains": strain,
            "sequences": payload,
        } if strain else {"sequences": payload}
    url = Config.DBAASP_STRAIN_URL if strain else Config.DBAASP_GENERAL_URL
    response = requests.post(url=url, data=request_data)
    status, response = response.status_code, response.json()
    if verbose:
        print(f"request status: {status}")
    return utils.clean_dbaasp_preds(pd.DataFrame(response[1:], columns=response[0]), strain) if status == 200 else None


def get_dbaasp_genome_predictions(payload: str, strain: str = "Escherichia coli ATCC 25922",
                                  genbank_id: int = 2137, verbose: bool = True) -> pd.DataFrame:
    if verbose:
        print("Sending prediction request to DBAASP...")
    request_data = {
        "strains": strain,
        "sequences": payload,
        "source": "my_computer",
    } if strain else {
        "sequences": payload,
        "strains": "",
        "source": "genbank",
        "genBankId": genbank_id,
        "genomeSequenceFile": "undefined",
    }
    url = Config.DBAASP_GENOME_URL
    response = requests.post(url=url, data=request_data)
    status, response = response.status_code, response.json()
    if verbose:
        print(f"request status: {status}")
    return utils.clean_dbaasp_genome_preds(pd.DataFrame(response[1:], columns=response[0]), strain) if status == 200 else None


def get_stm_predictions(payload: str, verbose: bool = True) -> pd.DataFrame:
    if verbose:
        print("Sending prediction request to STM...")
    response = requests.post(
        url=Config.STM_URL,
        data={
            "input": payload,
        })
    status, response = response.status_code, pd.read_html(response.text)[0]
    if verbose:
        print(f"request status: {status}")
    with io.StringIO(payload) as sequences:
        info = pd.DataFrame(
            ((s.id, str(s.seq)) for s in Bio.SeqIO.parse(sequences, "fasta")),
            columns=["id", "sequence"])
    response = pd.concat([info, response], axis="columns")
    return utils.clean_stm_preds(response) if status == 200 else None
