import io

import Bio
import pandas as pd
import requests

from classif.config import Config
from classif import utils


def predict_dbaasp(input_path: str, strain: str = "Escherichia coli ATCC 25922", verbose: bool = True) -> None:
    with open(input_path, 'r') as f:
        payload = f.readlines()
    result = (get_dbaasp_predictions("".join(chunk), strain, verbose)
              for chunk in utils.split_into_chunks(payload, chunk_size=Config.DBAASP_CHUNK_SIZE))
    result = pd.concat((partial for partial in result if partial is not None), axis="rows", ignore_index=True)
    out = input_path.replace(".fasta", f"_pred_dbaasp_{strain.replace(' ', '_')}.csv")
    if result is not None:
        result.to_csv(out, index=False)
    if verbose:
        print(f"saved predictions to {out}")


def get_dbaasp_predictions(payload: str, strain: str = "Escherichia coli ATCC 25922", verbose: bool = True) -> pd.DataFrame:
    if verbose:
        print("Sending prediction request to DBAASP...")
    response = requests.post(
        url=Config.DBAASP_URL,
        data={
            "strains": strain,
            "sequences": payload,
        })
    status, response = response.status_code, response.json()
    if verbose:
        print(f"request status: {status}")
    return utils.clean_dbaasp_preds(pd.DataFrame(response[1:], columns=response[0])) if status == 200 else None


def predict_stm(input_path: str, verbose: bool = True) -> None:
    with open(input_path, 'r') as f:
        payload = "".join(f.readlines())
    result = get_stm_predictions(payload, verbose)
    out = input_path.replace(".fasta", f"_pred_stm.csv")
    if result is not None:
        result.to_csv(out, index=False)
    if verbose:
        print(f"saved predictions to {out}")


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


def predict_ampscanner(input_path: str, strain: str, verbose: bool = True) -> None:
    return None
