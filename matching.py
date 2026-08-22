from __future__ import annotations

from itertools import combinations

import pandas as pd
from rapidfuzz import fuzz

import config


def _clean_text(value) -> str:
    if pd.isna(value):
        return ""
    return " ".join(str(value).strip().lower().split())


def _ensure_row_uid(df: pd.DataFrame, dataset_label: str) -> pd.DataFrame:
    df_work = df.reset_index(drop=True).copy()
    if "_row_uid" not in df_work.columns:
        df_work["_row_uid"] = [f"{dataset_label or 'row'}__{i}" for i in range(len(df_work))]
    else:
        missing = df_work["_row_uid"].isna() | (df_work["_row_uid"].astype(str).str.strip() == "")
        if missing.any():
            df_work.loc[missing, "_row_uid"] = [f"{dataset_label or 'row'}__{i}" for i in df_work.index[missing]]
    return df_work


def _ordered_pair(rec_a: dict, rec_b: dict) -> tuple[dict, dict]:
    ts_a = rec_a.get("timestamp_submit")
    ts_b = rec_b.get("timestamp_submit")
    try:
        if pd.notna(ts_a) and pd.notna(ts_b):
            parsed_a = pd.to_datetime(ts_a, errors="coerce")
            parsed_b = pd.to_datetime(ts_b, errors="coerce")
            if pd.notna(parsed_a) and pd.notna(parsed_b) and parsed_a > parsed_b:
                return rec_b, rec_a
    except Exception:
        pass
    return rec_a, rec_b


def _event_key(record: dict) -> str:
    title = _clean_text(record.get("judul_kegiatan"))
    date = _clean_text(record.get("tanggal_kegiatan"))
    return f"{title}||{date}"


def compute_pair_score(record_a: dict, record_b: dict) -> dict:
    nama_a, nama_b = _clean_text(record_a.get("nama")), _clean_text(record_b.get("nama"))
    dob_a, dob_b = _clean_text(record_a.get("tanggal_lahir")), _clean_text(record_b.get("tanggal_lahir"))
    kel_a, kel_b = _clean_text(record_a.get("kelurahan")), _clean_text(record_b.get("kelurahan"))
    area_a, area_b = _clean_text(record_a.get("area_program")), _clean_text(record_b.get("area_program"))

    score_nama = fuzz.token_sort_ratio(nama_a, nama_b) if nama_a and nama_b else 0.0
    score_dob = fuzz.ratio(dob_a, dob_b) if dob_a and dob_b else 0.0
    score_kelurahan = fuzz.ratio(kel_a, kel_b) if kel_a and kel_b else 0.0
    score_area = fuzz.ratio(area_a, area_b) if area_a and area_b else 0.0

    final_score = (
        score_nama * config.WEIGHT_NAMA
        + score_dob * config.WEIGHT_DOB
        + score_kelurahan * config.WEIGHT_KELURAHAN
        + score_area * config.WEIGHT_AREA
    )
    return {
        "score_nama": round(score_nama, 2),
        "score_dob": round(score_dob, 2),
        "score_kelurahan": round(score_kelurahan, 2),
        "score_area": round(score_area, 2),
        "final_score": round(final_score, 2),
    }


def compute_pair_score_register(record_a: dict, record_b: dict) -> dict:
    nama_a, nama_b = _clean_text(record_a.get("nama")), _clean_text(record_b.get("nama"))
    dob_a, dob_b = _clean_text(record_a.get("tanggal_lahir")), _clean_text(record_b.get("tanggal_lahir"))
    kk_a, kk_b = _clean_text(record_a.get("nama_kepala_keluarga")), _clean_text(record_b.get("nama_kepala_keluarga"))

    score_nama = fuzz.token_sort_ratio(nama_a, nama_b) if nama_a and nama_b else 0.0
    score_dob = fuzz.ratio(dob_a, dob_b) if dob_a and dob_b else 0.0
    score_kepala_keluarga = fuzz.token_sort_ratio(kk_a, kk_b) if kk_a and kk_b else 0.0

    final_score = (
        score_nama * config.WEIGHT_NAMA_REG
        + score_dob * config.WEIGHT_DOB_REG
        + score_kepala_keluarga * config.WEIGHT_KEPALA_KELUARGA_REG
    )
    return {
        "score_nama": round(score_nama, 2),
        "score_dob": round(score_dob, 2),
        "score_kepala_keluarga": round(score_kepala_keluarga, 2),
        "final_score": round(final_score, 2),
    }


def find_duplicate_pairs(
    df: pd.DataFrame,
    threshold: float = config.DUPLICATE_THRESHOLD,
    progress_callback=None,
    dataset_label: str = "Login",
) -> pd.DataFrame:
    """Global fuzzy pairwise matching for Login.

    Semua pasangan dibandingkan. Tidak ada gate judul/tanggal sebelum scoring.
    Event hanya digunakan sebagai konteks pada hasil review. Dengan demikian
    peserta yang sama pada kegiatan berbeda tetap muncul sebagai kandidat bila
    similarity >= threshold, tetapi reviewer dapat memilih Keep Both.
    """
    required = list(config.REQUIRED_MATCH_COLUMNS)
    missing_cols = [c for c in required if c not in df.columns]
    if missing_cols:
        raise ValueError(f"Kolom wajib untuk matching Login tidak ditemukan: {missing_cols}")
    if df.empty or len(df) < 2:
        return pd.DataFrame()

    df_work = _ensure_row_uid(df, dataset_label)
    records = df_work.to_dict("records")
    total_pairs = len(records) * (len(records) - 1) // 2
    results: list[dict] = []
    processed = 0

    for i, j in combinations(range(len(records)), 2):
        rec_a, rec_b = _ordered_pair(records[i], records[j])
        scores = compute_pair_score(rec_a, rec_b)
        processed += 1
        if progress_callback and (processed % 200 == 0 or processed == total_pairs):
            progress_callback(processed, total_pairs)
        if scores["final_score"] < threshold:
            continue
        same_event = _event_key(rec_a) == _event_key(rec_b) and _event_key(rec_a) != "||"
        results.append({
            "pair_id": f"{dataset_label}__{rec_a.get('_row_uid')}__{rec_b.get('_row_uid')}",
            "dataset": dataset_label,
            "row_uid_a": rec_a.get("_row_uid"),
            "row_uid_b": rec_b.get("_row_uid"),
            "id_a": rec_a.get("id_kobo"),
            "id_b": rec_b.get("id_kobo"),
            "custom_id_a": rec_a.get("custom_id"),
            "custom_id_b": rec_b.get("custom_id"),
            "judul_kegiatan_a": rec_a.get("judul_kegiatan"),
            "judul_kegiatan_b": rec_b.get("judul_kegiatan"),
            "tanggal_kegiatan_a": rec_a.get("tanggal_kegiatan"),
            "tanggal_kegiatan_b": rec_b.get("tanggal_kegiatan"),
            "same_event": same_event,
            "nama_a": rec_a.get("nama"),
            "nama_b": rec_b.get("nama"),
            "tanggal_lahir_a": rec_a.get("tanggal_lahir"),
            "tanggal_lahir_b": rec_a.get("tanggal_lahir") if False else rec_b.get("tanggal_lahir"),
            "kelurahan_a": rec_a.get("kelurahan"),
            "kelurahan_b": rec_b.get("kelurahan"),
            "area_program_a": rec_a.get("area_program"),
            "area_program_b": rec_b.get("area_program"),
            "timestamp_submit_a": rec_a.get("timestamp_submit"),
            "timestamp_submit_b": rec_b.get("timestamp_submit"),
            **scores,
            "status": "Potensi Double Count" if same_event else "Peserta Sama / Kegiatan Berbeda - Review",
        })

    if not results:
        return pd.DataFrame()
    return pd.DataFrame(results).sort_values(["final_score", "same_event"], ascending=[False, False]).reset_index(drop=True)


def find_duplicate_pairs_register(
    df_register: pd.DataFrame,
    threshold: float = config.DUPLICATE_THRESHOLD,
    progress_callback=None,
) -> pd.DataFrame:
    """Global fuzzy pairwise matching for Register.

    Tidak ada gate event. Jika dua record memiliki weighted similarity >=
    threshold, pasangan masuk Review Register. Kegiatan/tanggal hanya menjadi
    konteks untuk keputusan akhir panitia.
    """
    missing_cols = [c for c in config.REQUIRED_MATCH_COLUMNS_REGISTER if c not in df_register.columns]
    if missing_cols:
        raise ValueError(f"Kolom wajib untuk matching Register tidak ditemukan: {missing_cols}")
    if df_register.empty or len(df_register) < 2:
        return pd.DataFrame()

    df_work = _ensure_row_uid(df_register, "Register")
    records = df_work.to_dict("records")
    total_pairs = len(records) * (len(records) - 1) // 2
    results: list[dict] = []
    processed = 0

    for i, j in combinations(range(len(records)), 2):
        rec_a, rec_b = _ordered_pair(records[i], records[j])
        scores = compute_pair_score_register(rec_a, rec_b)
        processed += 1
        if progress_callback and (processed % 200 == 0 or processed == total_pairs):
            progress_callback(processed, total_pairs)
        if scores["final_score"] < threshold:
            continue
        same_event = _event_key(rec_a) == _event_key(rec_b) and _event_key(rec_a) != "||"
        results.append({
            "pair_id": f"Register__{rec_a.get('_row_uid')}__{rec_b.get('_row_uid')}",
            "dataset": "Register",
            "row_uid_a": rec_a.get("_row_uid"),
            "row_uid_b": rec_b.get("_row_uid"),
            "id_a": rec_a.get("id_kobo"),
            "id_b": rec_b.get("id_kobo"),
            "custom_id_a": rec_a.get("custom_id"),
            "custom_id_b": rec_b.get("custom_id"),
            "nama_a": rec_a.get("nama"),
            "nama_b": rec_b.get("nama"),
            "tanggal_lahir_a": rec_a.get("tanggal_lahir"),
            "tanggal_lahir_b": rec_b.get("tanggal_lahir"),
            "nama_kepala_keluarga_a": rec_a.get("nama_kepala_keluarga"),
            "nama_kepala_keluarga_b": rec_b.get("nama_kepala_keluarga"),
            "judul_kegiatan_a": rec_a.get("judul_kegiatan"),
            "judul_kegiatan_b": rec_b.get("judul_kegiatan"),
            "tanggal_kegiatan_a": rec_a.get("tanggal_kegiatan"),
            "tanggal_kegiatan_b": rec_b.get("tanggal_kegiatan"),
            "timestamp_submit_a": rec_a.get("timestamp_submit"),
            "timestamp_submit_b": rec_b.get("timestamp_submit"),
            "same_event": same_event,
            **scores,
            "status": "Potensi Double Register" if same_event else "Peserta Sama / Kegiatan Berbeda - Review",
        })

    if not results:
        return pd.DataFrame()
    return pd.DataFrame(results).sort_values(["final_score", "same_event"], ascending=[False, False]).reset_index(drop=True)


def check_person_logged_in_for_event(
    person_record: dict,
    df_login: pd.DataFrame,
    threshold: float = config.DUPLICATE_THRESHOLD,
) -> bool:
    if df_login.empty:
        return False
    target_event = _clean_text(person_record.get("judul_kegiatan"))
    target_date = _clean_text(person_record.get("tanggal_kegiatan"))
    if not target_event or not target_date:
        return False

    # Primary key match: canonical custom_id first.
    target_id = _clean_text(person_record.get("custom_id"))
    if target_id:
        for row in df_login.to_dict("records"):
            if _clean_text(row.get("judul_kegiatan")) != target_event:
                continue
            if _clean_text(row.get("tanggal_kegiatan")) != target_date:
                continue
            if _clean_text(row.get("custom_id")) == target_id:
                return True

    # Fallback fuzzy identity when custom_id is missing.
    for row in df_login.to_dict("records"):
        if _clean_text(row.get("judul_kegiatan")) != target_event:
            continue
        if _clean_text(row.get("tanggal_kegiatan")) != target_date:
            continue
        if compute_pair_score(person_record, row)["final_score"] >= threshold:
            return True
    return False


def find_registered_not_logged_in(
    df_login: pd.DataFrame,
    df_register: pd.DataFrame,
    threshold: float = config.DUPLICATE_THRESHOLD,
) -> pd.DataFrame:
    if df_register.empty:
        return df_register.copy()
    if df_login.empty:
        return df_register.copy()
    rows = [r for r in df_register.to_dict("records") if not check_person_logged_in_for_event(r, df_login, threshold)]
    return pd.DataFrame(rows).reset_index(drop=True) if rows else pd.DataFrame(columns=df_register.columns)
