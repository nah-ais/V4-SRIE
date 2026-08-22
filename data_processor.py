"""
data_processor.py
------------------
Helper untuk operasi data level-aplikasi:
  - Menyiapkan dataset gabungan (Login + Register) untuk matching.
  - Menerapkan keputusan reviewer (Simpan A/B, Keep keduanya).
  - Append data Register -> Login.
  - Export hasil akhir ke CSV/Excel.

Modul ini murni memanipulasi pandas DataFrame; tidak ada elemen UI di sini
supaya mudah di-unit-test terpisah dari Streamlit.
"""

from __future__ import annotations

import io
import pandas as pd

import config
from matching import check_person_logged_in_for_event
# find_earliest_register_date_for_person (fuzzy match) TIDAK dipakai lagi sejak
# custom_id tersedia di kedua form — lihat add_month_first_column() di bawah.
# Fungsinya tetap dipertahankan di matching.py sebagai cadangan/referensi.



def _norm_identity(value) -> str:
    """Normalisasi field identitas untuk canonicalisasi custom_id."""
    if pd.isna(value):
        return ""
    return " ".join(str(value).strip().lower().split())


def canonicalize_custom_ids(
    df_login: pd.DataFrame,
    df_register: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Menyatukan custom_id yang berbeda untuk orang yang sama tanpa menggabungkan
    record kegiatannya.

    Prinsip bisnis:
      - `custom_id` = identitas peserta, sehingga satu orang mempertahankan satu
        ID lintas kegiatan.
      - Satu baris Login/Register tetap merupakan record event tersendiri.
      - Jika peserta yang sama memiliki beberapa custom_id, ID dari submission
        pertama (berdasarkan timestamp_submit) menjadi canonical ID.
      - Identitas peserta ditentukan dari nama + tanggal lahir + kelurahan, bukan
        dari judul/tanggal kegiatan, sehingga orang yang sama di kegiatan berbeda
        tetap memakai custom_id yang sama.

    Fungsi ini TIDAK melakukan deduplikasi row.
    """
    login = df_login.copy()
    register = df_register.copy()

    frames = []
    for label, frame in (("Login", login), ("Register", register)):
        if frame.empty:
            continue
        work = frame.copy()
        for col in ("nama", "tanggal_lahir", "kelurahan"):
            if col not in work.columns:
                work[col] = ""
        if "custom_id" not in work.columns:
            work["custom_id"] = ""
        work["_source_dataset"] = label
        work["_source_order"] = range(len(work))
        work["_identity_key"] = (
            work["nama"].map(_norm_identity) + "||" +
            work["tanggal_lahir"].map(_norm_identity) + "||" +
            work["kelurahan"].map(_norm_identity)
        )
        work["_submit_dt"] = work.get("timestamp_submit", pd.Series(index=work.index)).map(_parse_event_date)
        frames.append(work)

    if not frames:
        return login, register

    combined = pd.concat(frames, ignore_index=True, sort=False)
    canonical = {}

    for key, group in combined.groupby("_identity_key", dropna=False):
        if not key or key == "||||":
            continue
        valid = group[group["custom_id"].notna() & (group["custom_id"].astype(str).str.strip() != "")].copy()
        if valid.empty:
            continue
        valid = valid.sort_values(
            by=["_submit_dt", "_source_order"],
            na_position="last",
            kind="stable",
        )
        canonical_id = str(valid.iloc[0]["custom_id"]).strip()
        canonical[key] = canonical_id

    combined["custom_id"] = combined.apply(
        lambda row: canonical.get(row["_identity_key"], row["custom_id"]),
        axis=1,
    )

    # Kembalikan ke dataset asal dan pertahankan urutan baris.
    login_out = combined[combined["_source_dataset"] == "Login"].sort_values("_source_order", kind="stable").drop(
        columns=["_source_dataset", "_source_order", "_identity_key", "_submit_dt"], errors="ignore"
    ).reset_index(drop=True)
    register_out = combined[combined["_source_dataset"] == "Register"].sort_values("_source_order", kind="stable").drop(
        columns=["_source_dataset", "_source_order", "_identity_key", "_submit_dt"], errors="ignore"
    ).reset_index(drop=True)

    # Pastikan schema kosong tetap sama seperti input.
    if login.empty:
        login_out = login
    if register.empty:
        register_out = register

    return login_out, register_out

def _parse_event_date(value):
    """
    Coba parse tanggal_kegiatan ke datetime untuk perbandingan 'acara terbaru'.

    Mencoba format umum secara berurutan agar robust terhadap variasi input
    dari Kobo (ISO 'YYYY-MM-DD', atau format lokal 'DD-MM-YYYY'/'DD/MM/YYYY'):
      1. Parse tanpa asumsi dayfirst (menangani ISO 'YYYY-MM-DD' dengan benar).
      2. Jika gagal (NaT), coba ulang dengan dayfirst=True (menangani 'DD-MM-YYYY').
    """
    if pd.isna(value):
        return pd.NaT
    parsed = pd.to_datetime(value, errors="coerce", dayfirst=False)
    if pd.isna(parsed):
        parsed = pd.to_datetime(value, errors="coerce", dayfirst=True)
    return parsed


# =========================================================
# KOLOM FISKAL UNTUK SHEET BTT (Date, Month, Fiscal Year)
# =========================================================
# Tahun fiskal organisasi dimulai Oktober, bukan Januari:
#   Bulan Oktober = bulan fiskal ke-1 ... September = bulan fiskal ke-12.
# Contoh: Agustus -> bulan fiskal ke-11 -> "11|Aug"
#         Juli     -> bulan fiskal ke-10 -> "10|Jul"
_MONTH_ABBR_EN = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}


def _fiscal_month_label(date: pd.Timestamp) -> str:
    """
    Format 'Month' ala fiskal: '{nomor_bulan_fiskal}|{singkatan_bulan}'.
    Oktober=1 ... September=12. Contoh: Agustus -> '11|Aug'.
    """
    fiscal_month_number = ((date.month - 10) % 12) + 1
    return f"{fiscal_month_number}|{_MONTH_ABBR_EN[date.month]}"


def _fiscal_year_label(date: pd.Timestamp) -> str:
    """
    Format 'Fiscal Year': 'FY' + 2 digit tahun.
    Bulan < Oktober -> tahun kalender sama. Bulan >= Oktober -> tahun + 1.
    Contoh: Agustus 2025 -> FY25. Oktober 2025 -> FY26.
    """
    fiscal_year_full = date.year + 1 if date.month >= 10 else date.year
    return f"FY{fiscal_year_full % 100:02d}"


def add_fiscal_columns(df_login: pd.DataFrame, date_column: str = "tanggal_kegiatan") -> pd.DataFrame:
    """
    Menambahkan 3 kolom turunan ke salinan df_login untuk kebutuhan sheet BTT:
      - 'Date'        : tanggal acara (dari kolom `date_column`), diformat 'YYYY-MM-DD'.
      - 'Month'       : label bulan fiskal, format '{no_bulan_fiskal}|{singkatan}'.
      - 'Fiscal Year' : format 'FYxx' (lihat _fiscal_year_label).

    Baris dengan tanggal yang tidak bisa di-parse akan dikosongkan (bukan error),
    supaya satu baris data bermasalah tidak menggagalkan seluruh proses export.

    Catatan: kolom 'Month (First)' (bulan pertama kali join, dari Register)
    SENGAJA TIDAK dihitung di sini — akan diimplementasikan setelah sistem ID
    peserta siap, supaya pencocokan Register -> Login akurat (bukan fuzzy-match
    yang berisiko salah pasang untuk keperluan pelaporan resmi seperti BTT).

    Returns
    -------
    pd.DataFrame
        Salinan df_login + kolom 'Date', 'Month', 'Fiscal Year'.
    """
    df = df_login.copy()

    if date_column not in df.columns or df.empty:
        df["Date"] = ""
        df["Month"] = ""
        df["Fiscal Year"] = ""
        return df

    parsed_dates = df[date_column].apply(_parse_event_date)

    df["Date"] = parsed_dates.apply(lambda d: d.strftime("%Y-%m-%d") if pd.notna(d) else "")
    df["Month"] = parsed_dates.apply(lambda d: _fiscal_month_label(d) if pd.notna(d) else "")
    df["Fiscal Year"] = parsed_dates.apply(lambda d: _fiscal_year_label(d) if pd.notna(d) else "")

    return df


def add_month_first_column(
    df_login: pd.DataFrame,
    df_register: pd.DataFrame,
    date_column: str = "tanggal_kegiatan",
) -> pd.DataFrame:
    """Add Month (First) using the earliest valid Register event date per participant.

    Primary lookup: custom_id. Fallback: normalized full name. This is intentionally
    independent of the Login event date because the value represents the participant's
    first registration/joining month.
    """
    df = df_login.copy()
    df["Month (First)"] = ""
    if df.empty or df_register.empty or date_column not in df_register.columns:
        return df

    reg = df_register.copy()
    reg["_parsed_date"] = reg[date_column].apply(_parse_event_date)
    reg = reg.dropna(subset=["_parsed_date"]).copy()
    if reg.empty:
        return df

    def clean_series(series):
        return series.fillna("").astype(str).str.strip()

    # Lookup tables by custom_id and, independently, by full name.
    id_map = {}
    if "custom_id" in reg.columns:
        for key, g in reg[clean_series(reg["custom_id"]) != ""].groupby(clean_series(reg["custom_id"]), sort=False):
            id_map[key] = g["_parsed_date"].min()

    name_map = {}
    if "nama" in reg.columns:
        names = clean_series(reg["nama"]).map(_norm_identity)
        for key, g in reg[names != ""].groupby(names, sort=False):
            name_map[key] = g["_parsed_date"].min()

    login_ids = clean_series(df.get("custom_id", pd.Series(index=df.index, dtype=object)))
    login_names = df.get("nama", pd.Series(index=df.index, dtype=object)).map(_norm_identity)

    def lookup(row):
        cid = str(row.get("_cid", "")).strip()
        name = str(row.get("_name", "")).strip()
        if cid and cid in id_map:
            return _fiscal_month_label(id_map[cid])
        if name and name in name_map:
            return _fiscal_month_label(name_map[name])
        return ""

    temp = pd.DataFrame({"_cid": login_ids, "_name": login_names}, index=df.index)
    df["Month (First)"] = temp.apply(lookup, axis=1)
    return df


# =========================================================
# KOLOM PROFIL / PROGRAM UNTUK SHEET BTT (dari Form Register)
# =========================================================
_AGE_GROUP_BINS = [
    (0, 5, "0-5"),
    (6, 11, "06-11"),
    (12, 17, "12-17"),
]

# Alias internal + variasi nama field yang umum keluar dari Kobo.
# Jika form berubah, tambahkan alias di sini tanpa mengubah logic BTT.
BTT_REGISTER_FIELD_ALIASES = {
    "Household Name": [
        "nama_kepala_keluarga", "Nama Kepala Keluarga", "household_name",
        "nama kepala keluarga", "kepala_keluarga",
    ],
    "Sex": [
        "jenis_kelamin", "Jenis Kelamin", "sex", "gender",
    ],
    "Age": [
        "usia", "Age", "age", "umur",
    ],
    "Disability Category": [
        "disability_category", "Disability Category", "kategori_disabilitas",
        "kategori_disability", "kategori disabilitas", "disability category",
    ],
    "Disability Status": [
        "disability_status", "Disability Status", "status_disabilitas",
        "status disabilitas", "disability status",
    ],
    "RC": [
        "rc", "RC", "relational_capital", "relational capital",
    ],
    "RC Status": [
        "rc_status", "RC Status", "status_rc", "status rc", "rc status", "IDN RC Status",
    ],
    "IDN": [
        "idn", "IDN", "idn_status", "IDN Status", "idn status",
    ],
    "MVC- Dimensi 1": [
        "mvc_dimensi_1", "MVC- Dimensi 1", "MVC Dimensi 1", "mvc_1", "mvc1",
        "mvc dimensi 1",
    ],
    "MVC- Dimensi 2": [
        "mvc_dimensi_2", "MVC- Dimensi 2", "MVC Dimensi 2", "mvc_2", "mvc2",
        "mvc dimensi 2",
    ],
    "MVC- Dimensi 3": [
        "mvc_dimensi_3", "MVC- Dimensi 3", "MVC Dimensi 3", "mvc_3", "mvc3",
        "mvc dimensi 3",
    ],
    "MVC- Dimensi 4": [
        "mvc_dimensi_4", "MVC- Dimensi 4", "MVC Dimensi 4", "mvc_4", "mvc4",
        "mvc dimensi 4",
    ],
    "SP - Cash transfers/food assistance": [
        "sp_cash_transfers", "SP - Cash transfers/food assistance",
        "cash_transfers", "food_assistance", "sp_cash", "sp_cash_transfer",
    ],
    "SP - Health assistance": [
        "sp_health_assistance", "SP - Health assistance", "health_assistance",
        "sp_health", "sp_healthcare",
    ],
    "SP - Education Assistance": [
        "sp_education_assistance", "SP - Education Assistance", "education_assistance",
        "sp_education", "education assistance",
    ],
    "Institution": ["institution", "Institution", "instansi"],
    "Position": ["position", "Position", "jabatan"],
    "No.Handphone (WA)": [
        "nomor_hp", "no_handphone", "No.Handphone (WA)", "nomor_handphone",
        "nomor wa", "no hp", "phone", "whatsapp", "wa",
    ],
    "# Child <5": [
        "child_under_5", "# Child <5", "jumlah_child_under_5", "jumlah anak <5",
        "child <5", "child_0_5", "jumlah_anak_0_5",
    ],
    "# Child 6-11": [
        "child_6_11", "# Child 6-11", "jumlah_child_6_11", "jumlah anak 6-11",
        "child 6-11", "child_6_11_count", "jumlah_anak_6_11",
    ],
    "# Child 12-17": [
        "child_12_17", "# Child 12-17", "jumlah_child_12_17", "jumlah anak 12-17",
        "child 12-17", "child_12_17_count", "jumlah_anak_12_17",
    ],
}

_SEX_LABEL_MAP = {
    "laki-laki": "Male",
    "laki laki": "Male",
    "male": "Male",
    "perempuan": "Female",
    "female": "Female",
}


def _age_group_label(age) -> str:
    if pd.isna(age):
        return ""
    try:
        age_int = int(float(age))
    except (ValueError, TypeError):
        return ""
    if age_int < 0:
        return ""
    for low, high, label in _AGE_GROUP_BINS:
        if low <= age_int <= high:
            return label
    return "18+"


def _category_label(age) -> str:
    if pd.isna(age):
        return ""
    try:
        age_int = int(float(age))
    except (ValueError, TypeError):
        return ""
    if age_int < 0:
        return ""
    return "Child" if age_int < 18 else "Adult"


def _sex_label(raw_value) -> str:
    if pd.isna(raw_value):
        return ""
    key = str(raw_value).strip().lower()
    return _SEX_LABEL_MAP.get(key, str(raw_value).strip())


def _normalize_field_name(value) -> str:
    """Normalisasi nama kolom untuk resolver field Register."""
    import re
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def _is_empty(value) -> bool:
    if pd.isna(value):
        return True
    text = str(value).strip().lower()
    return text in {"", "nan", "none", "null", "na", "n/a", "-"}


def _first_non_empty(values):
    for value in values:
        if not _is_empty(value):
            return value
    return ""


def _resolve_register_column(df: pd.DataFrame, aliases: list[str]) -> str | None:
    """Cari field Register dengan exact normalized match lalu token match."""
    if df.empty:
        return None

    normalized = {_normalize_field_name(col): col for col in df.columns}
    alias_norms = [_normalize_field_name(alias) for alias in aliases]

    # 1) exact match
    for alias in alias_norms:
        if alias in normalized:
            return normalized[alias]

    # 2) contains all token kelompok alias (berguna untuk path Kobo panjang)
    candidates = []
    for alias in alias_norms:
        tokens = [t for t in alias.split("_") if t]
        if len(tokens) < 1:
            continue
        for norm_col, original in normalized.items():
            if all(token in norm_col for token in tokens):
                candidates.append((len(norm_col), original))
    if candidates:
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]

    return None


# Alias field ID kustom mentah dari Kobo (mis. hasil dynamic data attachment
# `instance()` pada form Login yang mengambil ID dari Register). Nama field
# asli di Kobo bisa bervariasi tergantung setup form, jadi dicari via alias.
CUSTOM_ID_FIELD_ALIASES = [
    "custom_id", "cek_ID", "cek_id", "CekID", "id_peserta", "ID_Peserta",
    "id_kustom", "participant_id", "ID Peserta", "kode_id", "kode_peserta",
]


def resolve_custom_id_column(df: pd.DataFrame) -> pd.DataFrame:
    """
    Memastikan kolom 'custom_id' terisi dari field ID mentah Kobo (apa pun nama
    aslinya, dicari via CUSTOM_ID_FIELD_ALIASES) SEBELUM proses matching/BTT.

    Dipanggil sekali segera setelah fetch/upload data (lihat app.py), baik untuk
    df_login maupun df_register. Kolom mentah aslinya TETAP dipertahankan untuk
    audit — hanya disalin nilainya ke kolom standar 'custom_id'.

    Jika kolom 'custom_id' sudah ada dan sudah terisi, tidak ada perubahan.
    Jika kosong tapi ditemukan kolom alias mentah, nilainya diisi dari sana.
    """
    if df.empty:
        return df

    df = df.copy()
    resolved_col = _resolve_register_column(df, CUSTOM_ID_FIELD_ALIASES)

    if "custom_id" not in df.columns:
        df["custom_id"] = ""

    if resolved_col and resolved_col != "custom_id":
        raw_values = df[resolved_col].fillna("").astype(str).str.strip()
        current = df["custom_id"].fillna("").astype(str).str.strip()
        # Isi custom_id dari kolom mentah HANYA pada baris yang custom_id-nya
        # masih kosong, supaya tidak menimpa custom_id yang sudah benar.
        df["custom_id"] = current.where(current != "", raw_values)

    return df


def _build_register_profile_lookup(df_register: pd.DataFrame):
    """Lookup profil Register by custom_id then full name, memakai semua row Register."""
    if df_register is None or df_register.empty:
        return {}, {}

    reg = df_register.copy()
    id_col = _resolve_register_column(reg, ["custom_id", "cek_ID", "id", "ID"])
    name_col = _resolve_register_column(reg, ["nama", "nama_lengkap_parent", "nama_child", "full_name", "Full Name"])
    date_col = _resolve_register_column(reg, ["tanggal_kegiatan", "tanggal_register", "registration_date", "_submission_time", "timestamp_submit"])

    field_source = {
        field: _resolve_register_column(reg, aliases)
        for field, aliases in BTT_REGISTER_FIELD_ALIASES.items()
    }

    reg["_profile_id_key"] = reg[id_col].map(_norm_identity) if id_col else ""
    reg["_profile_name_key"] = reg[name_col].map(_norm_identity) if name_col else ""
    if date_col:
        reg["_profile_date"] = reg[date_col].map(_parse_event_date)
    else:
        reg["_profile_date"] = pd.NaT

    def aggregate(group: pd.DataFrame) -> dict:
        record = {}
        for field, source_col in field_source.items():
            record[field] = _first_non_empty(group[source_col].tolist()) if source_col else ""
        valid_dates = group["_profile_date"].dropna()
        record["_first_registration_date"] = valid_dates.min() if not valid_dates.empty else pd.NaT
        return record

    by_id = {}
    id_mask = reg["_profile_id_key"] != ""
    for key, group in reg.loc[id_mask].groupby("_profile_id_key", sort=False):
        by_id[key] = aggregate(group)

    by_name = {}
    name_mask = reg["_profile_name_key"] != ""
    for key, group in reg.loc[name_mask].groupby("_profile_name_key", sort=False):
        by_name[key] = aggregate(group)

    return by_id, by_name


def _profile_for_row(row: pd.Series, by_id: dict, by_name: dict) -> dict:
    cid = _norm_identity(row.get("custom_id", ""))
    name = _norm_identity(row.get("nama", ""))
    if cid and cid in by_id:
        return by_id[cid]
    if name and name in by_name:
        return by_name[name]
    return {}


def _yes(value) -> bool:
    if pd.isna(value):
        return False
    return str(value).strip().lower() in {"yes", "y", "true", "1"}


def add_participant_profile_columns(df_login: pd.DataFrame, df_register: pd.DataFrame) -> pd.DataFrame:
    """Enrich BTT dari Register menggunakan ID, fallback Full Name."""
    df = df_login.copy()
    df["ID"] = df.get("custom_id", pd.Series(index=df.index, dtype=object)).fillna("")
    df["Full Name"] = df.get("nama", pd.Series(index=df.index, dtype=object)).fillna("")

    by_id, by_name = _build_register_profile_lookup(df_register)
    profiles = [_profile_for_row(row, by_id, by_name) for _, row in df.iterrows()]

    # Field source from Register
    register_output_fields = [
        "Household Name", "Sex", "Age",
        "Disability Category", "Disability Status",
        "RC", "RC Status", "IDN",
        "MVC- Dimensi 1", "MVC- Dimensi 2", "MVC- Dimensi 3", "MVC- Dimensi 4",
        "SP - Cash transfers/food assistance", "SP - Health assistance", "SP - Education Assistance",
        "Institution", "Position", "No.Handphone (WA)",
        "# Child <5", "# Child 6-11", "# Child 12-17",
    ]

    for field in register_output_fields:
        df[field] = [_first_non_empty([profile.get(field, "")]) for profile in profiles]

    # Standarisasi Sex: Laki-laki -> Male, Perempuan -> Female.
    df["Sex"] = df["Sex"].apply(_sex_label)

    # Derived fields
    df["Age group"] = df["Age"].apply(_age_group_label)
    df["Category"] = df["Age"].apply(_category_label)

    mvc_fields = [
        "MVC- Dimensi 1", "MVC- Dimensi 2", "MVC- Dimensi 3", "MVC- Dimensi 4"
    ]
    df["MVC"] = df.apply(
        lambda row: "Yes" if sum(_yes(row.get(field, "")) for field in mvc_fields) >= 2 else "No",
        axis=1,
    )

    sp_fields = [
        "SP - Cash transfers/food assistance",
        "SP - Health assistance",
        "SP - Education Assistance",
    ]
    df["Social Protection"] = df.apply(
        lambda row: "Yes" if any(_yes(row.get(field, "")) for field in sp_fields) else "No",
        axis=1,
    )

    return df


def add_btt_register_columns(df_login: pd.DataFrame, df_register: pd.DataFrame) -> pd.DataFrame:
    """Alias publik untuk enrichment Register ke BTT."""
    return add_participant_profile_columns(df_login, df_register)


def resolve_register_duplicate(
    df_login: pd.DataFrame,
    df_register: pd.DataFrame,
    pair_row: pd.Series,
    decision: str,
    threshold: float = config.DUPLICATE_THRESHOLD,
) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """
    Implementasi lengkap flowchart penanganan duplikat Register:

        Duplikat?
          -> Ya: cek acaranya sama? (informasional saja, keputusan sama)
               -> cek apakah di absensi (Login) sudah ada untuk ACARA TERBARU
                  dari pasangan duplikat ini?
                     -> Ya: tidak perlu menambahkan apa-apa.
                     -> Tidak: append data acara terbaru itu ke Login,
                               lalu hapus salah satu data duplikat di Register.
          -> Tidak (decision == "keep_both"): aman, tidak ada tindakan otomatis
             (dianggap dua orang berbeda).

    Parameters
    ----------
    df_login, df_register : pd.DataFrame
        Dataset saat ini (SEBELUM perubahan apa pun untuk pair ini).
    pair_row : pd.Series
        Satu baris dari hasil find_duplicate_pairs_register (harus punya
        id_a, id_b, judul_kegiatan_a/b, tanggal_kegiatan_a/b, timestamp_submit_a/b).
    decision : str
        "keep_a", "keep_b", atau "keep_both".
    threshold : float
        Ambang batas similarity untuk cek keberadaan di Login.

    Returns
    -------
    (df_login_baru, df_register_baru, info_message)
        info_message : penjelasan tindakan otomatis yang terjadi, untuk
        ditampilkan ke panitia di UI (transparansi keputusan sistem).
    """
    row_uid_a = pair_row.get("row_uid_a")
    row_uid_b = pair_row.get("row_uid_b")
    id_a, id_b = pair_row.get("id_a"), pair_row.get("id_b")

    if decision == "keep_both":
        # "aman" — dianggap dua orang berbeda, tidak ada tindakan otomatis.
        return df_login, df_register, (
            "Kedua data dianggap peserta yang BERBEDA — tidak ada perubahan otomatis. "
            "Masing-masing tetap akan dicek kelengkapan Login-nya secara normal via Auto-Append."
        )

    if decision not in ("keep_a", "keep_b"):
        raise ValueError(f"Decision tidak dikenal: {decision}")

    # ---- STEP 1: Hapus salah satu duplikat di Register sesuai keputusan panitia ----
    if "_row_uid" in df_register.columns and row_uid_a is not None and row_uid_b is not None:
        drop_uid = row_uid_b if decision == "keep_a" else row_uid_a
        df_register_new = df_register[df_register["_row_uid"] != drop_uid].reset_index(drop=True)
    else:
        drop_id = id_b if decision == "keep_a" else id_a
        df_register_new = df_register[df_register["id_kobo"] != drop_id].reset_index(drop=True)

    # ---- STEP 2: Tentukan "acara terbaru" di antara A dan B ----
    # Prioritas pembanding: tanggal_kegiatan (tanggal acara sebenarnya).
    # Fallback: timestamp_submit (waktu submit form) jika tanggal_kegiatan kosong/tidak valid.
    date_a = _parse_event_date(pair_row.get("tanggal_kegiatan_a"))
    date_b = _parse_event_date(pair_row.get("tanggal_kegiatan_b"))

    if pd.notna(date_a) and pd.notna(date_b):
        latest_id = id_b if date_b >= date_a else id_a
    elif pd.notna(date_a):
        latest_id = id_a
    elif pd.notna(date_b):
        latest_id = id_b
    else:
        ts_a, ts_b = pair_row.get("timestamp_submit_a"), pair_row.get("timestamp_submit_b")
        latest_id = id_b if (pd.notna(ts_b) and (pd.isna(ts_a) or ts_b >= ts_a)) else id_a

    # Ambil data lengkap baris "acara terbaru" dari df_register ASLI (sebelum dihapus),
    # supaya datanya tetap tersedia untuk di-append meskipun baris itu yang akan dihapus.
    latest_row_uid = row_uid_b if latest_id == id_b else row_uid_a
    if "_row_uid" in df_register.columns and latest_row_uid is not None:
        latest_row_df = df_register[df_register["_row_uid"] == latest_row_uid]
    else:
        latest_row_df = df_register[df_register["id_kobo"] == latest_id]

    if latest_row_df.empty:
        return df_login, df_register_new, "⚠️ Data acara terbaru tidak ditemukan, tidak ada tindakan otomatis."
    latest_row = latest_row_df.iloc[0].to_dict()
    event_label = latest_row.get("judul_kegiatan", "-")

    # ---- STEP 3: Cek apakah sudah ada di Login untuk acara terbaru tsb ----
    already_logged = check_person_logged_in_for_event(latest_row, df_login, threshold)

    if already_logged:
        info = (
            f"✅ Data untuk kegiatan **'{event_label}'** SUDAH ada di Login — "
            "tidak perlu menambahkan apa-apa (sesuai flowchart)."
        )
        return df_login, df_register_new, info

    # ---- STEP 4: Belum ada di Login -> append otomatis ----
    append_key = latest_row_uid if "_row_uid" in df_register.columns and latest_row_uid is not None else latest_id
    df_login_new = append_register_to_login(df_login, df_register, [append_key])
    info = (
        f"➕ Data untuk kegiatan **'{event_label}'** BELUM ada di Login — "
        "otomatis di-append ke dataset Login."
    )
    return df_login_new, df_register_new, info


def apply_review_decision(
    df: pd.DataFrame,
    pair_row: pd.Series,
    decision: str,
) -> pd.DataFrame:
    """
    Menerapkan keputusan panitia terhadap satu pasangan duplikat.

    Bersifat generik: dipakai untuk dataset LOGIN (dedup sederhana, tanpa
    logika auto-append lanjutan — karena Login memang sudah menandakan
    kehadiran, tidak perlu di-append ke mana pun).

    Untuk dataset REGISTER, gunakan `resolve_register_duplicate()` sebagai
    gantinya, karena Register butuh logika tambahan (cek & append ke Login
    untuk acara terbaru) sesuai flowchart bisnis.

    Parameters
    ----------
    df : pd.DataFrame
        Dataset asal pasangan (biasanya df_login).
    decision : str
        Salah satu dari: "keep_a", "keep_b", "keep_both"

    Returns
    -------
    df yang sudah diperbarui.
    """
    row_uid_a = pair_row.get("row_uid_a")
    row_uid_b = pair_row.get("row_uid_b")
    id_a = pair_row.get("id_a")
    id_b = pair_row.get("id_b")

    if decision == "keep_a":
        if "_row_uid" in df.columns and row_uid_b is not None:
            df = df[df["_row_uid"] != row_uid_b]
        else:
            df = df[df["id_kobo"] != id_b]

    elif decision == "keep_b":
        if "_row_uid" in df.columns and row_uid_a is not None:
            df = df[df["_row_uid"] != row_uid_a]
        else:
            df = df[df["id_kobo"] != id_a]

    elif decision == "keep_both":
        pass  # tidak ada perubahan, keduanya dipertahankan (misal beda kegiatan/valid)

    else:
        raise ValueError(f"Decision tidak dikenal: {decision}")

    return df.reset_index(drop=True)


def append_register_to_login(
    df_login: pd.DataFrame,
    df_register: pd.DataFrame,
    row_uids_to_append: list,
) -> pd.DataFrame:
    """
    Append submission Register tertentu ke Login.

    `_row_uid` diprioritaskan karena `id_kobo` dapat sama pada kegiatan berbeda.
    """
    if not row_uids_to_append:
        return df_login

    if "_row_uid" in df_register.columns:
        rows_to_append = df_register[df_register["_row_uid"].isin(row_uids_to_append)].copy()
    else:
        rows_to_append = df_register[df_register["id_kobo"].isin(row_uids_to_append)].copy()

    if rows_to_append.empty:
        return df_login

    # Selaraskan skema kolom dengan df_login; kolom hilang diisi NA
    login_cols = df_login.columns.tolist()
    for col in login_cols:
        if col not in rows_to_append.columns:
            rows_to_append[col] = pd.NA
    rows_to_append = rows_to_append[login_cols]

    df_login_new = pd.concat([df_login, rows_to_append], ignore_index=True)
    return df_login_new


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    """Konversi DataFrame ke bytes CSV (siap dipakai st.download_button)."""
    buffer = io.StringIO()
    df.to_csv(buffer, index=False)
    return buffer.getvalue().encode("utf-8-sig")  # utf-8-sig agar aman dibuka Excel


def to_excel_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    """
    Konversi beberapa DataFrame ke satu file Excel multi-sheet.

    Parameters
    ----------
    sheets : dict
        {"NamaSheet": dataframe, ...}
    """
    buffer = io.BytesIO()
    try:
        with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
            for sheet_name, df in sheets.items():
                safe_name = sheet_name[:31]  # batas nama sheet Excel
                df.to_excel(writer, sheet_name=safe_name, index=False)
    except ModuleNotFoundError as e:
        raise RuntimeError(
            "Library 'xlsxwriter' belum terpasang. Jalankan: pip install xlsxwriter"
        ) from e
    return buffer.getvalue()
