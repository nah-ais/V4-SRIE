"""
config.py
---------
Konfigurasi terpusat: mapping kolom KoboToolbox, bobot scoring,
threshold, dan konstanta lain yang dipakai di seluruh aplikasi.

Memusatkan konfigurasi di sini memudahkan maintenance jika suatu saat
struktur form Kobo berubah (tambah field, ganti nama field, dsb).
"""

# =========================================================
# 1. MAPPING KOLOM KOBOTOOLBOX -> NAMA KOLOM INTERNAL
# =========================================================

LOGIN_COLUMN_MAP = {
    "_id": "id_kobo",
    "_submission_time": "timestamp_submit",
    "nama_child": "nama",
    "tgl_lahir_child": "tanggal_lahir",
    "Kelurahan": "kelurahan",
    "Tuliskan_Kelurahannya": "kelurahan_lainnya",
    "group_ys5yz58/Area_Program": "area_program",
    "group_ys5yz58/Judul_Kegiatan": "judul_kegiatan",
    "group_ys5yz58/Tanggal_Kegiatan": "tanggal_kegiatan",
}

REGISTER_COLUMN_MAP = {
    "_id": "id_kobo",
    "_submission_time": "timestamp_submit",
    "group_digital_absensi/group_informasi_respondent/nama_lengkap_parent": "nama",
    "group_digital_absensi/group_informasi_respondent/tgl_lahir_parent": "tanggal_lahir",
    "group_digital_absensi/group_informasi_respondent/Jenis_Kelamin": "jenis_kelamin",
    "group_digital_absensi/group_informasi_respondent/usia": "usia",
    "group_digital_absensi/group_informasi_respondent/Nama_Kepala_Keluarga": "nama_kepala_keluarga",
    "group_digital_absensi/group_informasi_respondent/Kelurahan": "kelurahan",
    "group_digital_absensi/group_informasi_respondent/Tuliskan_Kelurahannya": "kelurahan_lainnya",
    "group_digital_absensi/group_informasi_respondent/RT": "rt",
    "group_digital_absensi/group_informasi_respondent/RW": "rw",
    "group_digital_absensi/group_informasi_respondent/Nomor_WA_HP": "nomor_hp",
    "group_digital_absensi/group_wx4wq68/Area_Program": "area_program",
    "group_digital_absensi/group_wx4wq68/Judul_Kegiatan": "judul_kegiatan",
    "group_digital_absensi/group_wx4wq68/Tanggal_Kegiatan": "tanggal_kegiatan",
    "group_digital_absensi/group_informasi_respondent/Apakah_Anda_memiliki_kebutuhan": "tipe_disabilitas",
    "group_digital_absensi/group_informasi_respondent/Kategori_Peserta": "kategori_peserta",
}

# =========================================================
# 1b. FIELD REGISTER TAMBAHAN UNTUK BTT
# =========================================================
# Alias digunakan saat response Kobo menyimpan nama field yang panjang
# (misalnya group_xxx/.../nama_field). Resolver di kobo_api.py akan
# mencari exact normalized name lalu token yang terkandung pada nama field.
BTT_REGISTER_COLUMN_ALIASES = {
    "disability_category": ["disability_category", "Disability Category", "kategori_disabilitas", "kategori disability"],
    "disability_status": ["disability_status", "Disability Status", "status_disabilitas", "status disability"],
    "rc": ["rc", "RC", "relational_capital"],
    "rc_status": ["rc_status", "RC Status", "status_rc", "idn rc status"],
    "idn": ["idn", "IDN", "idn_status"],
    "mvc_dimensi_1": ["mvc_dimensi_1", "MVC- Dimensi 1", "MVC Dimensi 1", "mvc1", "mvc_1"],
    "mvc_dimensi_2": ["mvc_dimensi_2", "MVC- Dimensi 2", "MVC Dimensi 2", "mvc2", "mvc_2"],
    "mvc_dimensi_3": ["mvc_dimensi_3", "MVC- Dimensi 3", "MVC Dimensi 3", "mvc3", "mvc_3"],
    "mvc_dimensi_4": ["mvc_dimensi_4", "MVC- Dimensi 4", "MVC Dimensi 4", "mvc4", "mvc_4"],
    "sp_cash_transfers": ["sp_cash_transfers", "SP - Cash transfers/food assistance", "cash_transfers", "food_assistance", "sp_cash"],
    "sp_health_assistance": ["sp_health_assistance", "SP - Health assistance", "health_assistance", "sp_health"],
    "sp_education_assistance": ["sp_education_assistance", "SP - Education Assistance", "education_assistance", "sp_education"],
    "institution": ["institution", "Institution", "instansi"],
    "position": ["position", "Position", "jabatan"],
    "nomor_hp": ["nomor_hp", "No.Handphone (WA)", "nomor_handphone", "nomor wa", "whatsapp", "phone"],
    "child_under_5": ["child_under_5", "# Child <5", "jumlah_child_under_5", "child 0 5", "child <5"],
    "child_6_11": ["child_6_11", "# Child 6-11", "jumlah_child_6_11", "child 6 11"],
    "child_12_17": ["child_12_17", "# Child 12-17", "jumlah_child_12_17", "child 12 17"],
}

# Kolom minimal yang WAJIB ada supaya proses matching LOGIN bisa berjalan
REQUIRED_MATCH_COLUMNS = ["nama", "tanggal_lahir", "kelurahan", "area_program"]

# Kolom minimal yang WAJIB ada supaya proses matching REGISTER bisa berjalan
REQUIRED_MATCH_COLUMNS_REGISTER = ["nama", "tanggal_lahir", "nama_kepala_keluarga"]

# Kolom yang dipakai sebagai GATE (filter wajib) sebelum similarity dihitung
# — HANYA berlaku untuk dataset LOGIN. Duplikasi Login hanya dicek antar baris
# yang memiliki judul_kegiatan SAMA PERSIS (setelah dinormalisasi: strip + lower).
# Jika judul_kegiatan berbeda, pasangan tersebut TIDAK dibandingkan sama sekali
# (otomatis dianggap unik / di-keep), karena satu orang wajar hadir di banyak kegiatan.
#
# Dataset REGISTER TIDAK memakai gate ini — pengecekan Register dilakukan
# GLOBAL lintas seluruh baris (tanpa peduli judul_kegiatan), karena identitas
# peserta di form Register seharusnya unik secara keseluruhan, bukan per kegiatan.
DUPLICATE_GATE_COLUMN = "judul_kegiatan"

# Kolom yang dipakai untuk ditampilkan di UI reviewer (urutan tampil)
DISPLAY_COLUMNS = [
    "id_kobo",
    "nama",
    "tanggal_lahir",
    "kelurahan",
    "area_program",
    "judul_kegiatan",
    "tanggal_kegiatan",
    "timestamp_submit",
]

# =========================================================
# 2. BOBOT SCORING (WEIGHTED SIMILARITY)
# =========================================================
# --- Skema untuk dataset LOGIN/ABSENSI ---
# Dicek per judul_kegiatan (gate), karena orang boleh hadir di banyak kegiatan.
WEIGHT_NAMA = 0.45
WEIGHT_DOB = 0.25
WEIGHT_KELURAHAN = 0.20
WEIGHT_AREA = 0.10

# Validasi total bobot = 1.0 (100%)
assert abs((WEIGHT_NAMA + WEIGHT_DOB + WEIGHT_KELURAHAN + WEIGHT_AREA) - 1.0) < 1e-6, \
    "Total bobot scoring Login harus = 1.0"

# --- Skema untuk dataset REGISTER ---
# Register harus benar-benar UNIK secara global (lintas kegiatan, TIDAK di-gate
# oleh judul_kegiatan), karena satu orang seharusnya hanya register SEKALI saja
# meskipun dia nantinya ikut banyak kegiatan. Fokus pembanding: Nama, Tanggal
# Lahir, dan Nama Kepala Keluarga (identitas keluarga membantu memastikan
# apakah ini benar orang/keluarga yang sama).
WEIGHT_NAMA_REG = 0.45
WEIGHT_DOB_REG = 0.30
WEIGHT_KEPALA_KELUARGA_REG = 0.25

assert abs((WEIGHT_NAMA_REG + WEIGHT_DOB_REG + WEIGHT_KEPALA_KELUARGA_REG) - 1.0) < 1e-6, \
    "Total bobot scoring Register harus = 1.0"

# =========================================================
# 3. THRESHOLD ATURAN
# =========================================================
DUPLICATE_THRESHOLD = 95.0  # >= nilai ini => "Potensi Double Count"

# =========================================================
# 4. KOBOTOOLBOX API DEFAULT
# =========================================================
# Ambil token API di: https://kf.kobotoolbox.org/token/?format=json
# CATATAN KEAMANAN: menyimpan token langsung di source code hanya disarankan
# untuk penggunaan lokal/internal. Untuk deployment (Streamlit Cloud, dsb),
# gunakan st.secrets atau environment variable, JANGAN commit token ke repo publik.
KOBO_TOKEN = "c710cac4d6d5fafbda973f04b30a2c27bda914c4"  # ganti dengan token API pribadi Anda

KOBO_ENDPOINT = "https://kf.kobotoolbox.org/api/v2"
KOBO_API_BASE_URL = KOBO_ENDPOINT  # alias, dipakai oleh kobo_api.py

# Asset UID (Form UID) masing-masing form Kobo.
# Setiap form punya UID unik yang bisa dilihat di URL form tersebut
# di dashboard KoboToolbox (kf.kobotoolbox.org/#/forms/<UID>/...).
FORM_UID_REGISTRASI = "aRVadKAkpz2PYMaZH2gXKU"  # Form UID khusus Registrasi
FORM_UID_LOGIN = "aE3xS8zXQsU9KQsiT9T7PA"  # TODO: isi dengan Form UID khusus Login/Absensi Anda

KOBO_REQUEST_TIMEOUT = 30  # detik

# =========================================================
# 4b. MAPPING AREA PROGRAM (AP) -> ASSET UID (LOGIN & REGISTER)
# =========================================================
# Tambahkan/ubah daftar AP di sini. Panitia tinggal pilih dari dropdown
# di sidebar, lalu Asset UID Login & Register akan terisi otomatis.
AP_ASSET_MAP = {
    "AP-Surabaya": {
        "login": "ISI_ASSET_UID_LOGIN_SURABAYA",
        "register": "ISI_ASSET_UID_REGISTER_SURABAYA",
    },
    "AP-Kalimantan Barat": {
        "login": "ISI_ASSET_UID_LOGIN_KALBAR",
        "register": "ISI_ASSET_UID_REGISTER_KALBAR",
    },
}

# =========================================================
# 5. SESSION STATE KEYS (biar konsisten, hindari typo string literal)
# =========================================================
SS_LOGIN_DF = "df_login"
SS_REGISTER_DF = "df_register"
SS_DUPLICATE_PAIRS_LOGIN = "df_duplicate_pairs_login"
SS_DUPLICATE_PAIRS_REGISTER = "df_duplicate_pairs_register"
SS_REVIEW_DECISIONS_LOGIN = "review_decisions_login"     # dict: pair_id -> keputusan (dataset Login)
SS_REVIEW_DECISIONS_REGISTER = "review_decisions_register"  # dict: pair_id -> keputusan (dataset Register)
SS_NOT_LOGIN_YET = "df_not_login_yet"
SS_APPENDED_IDS = "appended_ids"             # id_kobo dari register yang sudah di-append ke login

# =========================================================
# 6. METADATA PROJECT (INPUT MANUAL PANITIA -> DUPLICATE KE SEMUA BARIS)
# =========================================================
# Field-field ini diketik SEKALI oleh panitia di UI, lalu nilainya
# di-duplicate ke seluruh baris dataset Login & Register sebelum export.
PROJECT_METADATA_FIELDS = [
    "Implementor",
    "Sector",
    "CPM",
    "Project",
    "Project Category",
    "Activity Code",
    "Activity",
    "Activity Detail",
]

SS_PROJECT_METADATA = "project_metadata"  # dict: field -> value yang diisi panitia
SS_METADATA_APPLIED = "project_metadata_applied"  # bool: sudah diterapkan ke dataset atau belum
