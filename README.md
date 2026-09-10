# UAV Photo Optimizer

獨立於 UDAS 的本機航拍照片減量工具。Python 3.11+、ExifTool、pyproj；不需要雲端服務。版本 0.1.0 提供命令列工具，沒有圖形介面。

預設最低保留前向重疊率 **80%**，可調整。先將高重疊照片列為候選，若前後保留照片銜接不足，整段候選回補。原始照片不修改、不移動、不刪除。預設只輸出報告，`--copy` 才複製保留照片。

## 安裝

在本專案目錄執行（macOS）：

```sh
brew install exiftool
export LC_ALL=en_US.UTF-8
export PYTHONUTF8=1
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

本次已完成本機安裝。UTF-8 locale 避免 ASCII locale 下中文路徑造成 editable install 或啟動失敗；每個新終端機工作階段需設定上述環境變數，也可直接使用 `./run` 代替 `.venv/bin/uav-optimize`（macOS 啟動器自動設定）。Windows／Linux 亦須先安裝 ExifTool 並加入 PATH；虛擬環境執行檔路徑及可用的 UTF-8 locale 依平台調整。

重現本次 Python 相依套件可先安裝 `requirements.lock`，再執行 `pip install --no-deps -e .`。ExifTool 實際版本記於每次 summary。

## 直接掃描現有照片

```sh
.venv/bin/uav-optimize ../UserUpload-original --output outputs/my-scan
```

每次使用新的輸出資料夾。預設門檻是 **3,000,000,000 bytes OR 1,000 張**；未達門檻仍掃描及輸出清單，全部保留。`--force` 可對小批資料測試減量，但不會略過幾何保護條件。

```sh
.venv/bin/uav-optimize ../UserUpload-original --output outputs/my-forced-scan --force
```

現有照片屬 Autel XT701；原始 XMP 欄位會保留，但不將其 `AboveGroundAltitude` 自動視為可信 AGL。沒有可信離地高度、經確認的相機 profile 或標準化角度時，工具會保留該照片。**看到保留全部不代表已驗證可建模，也不代表這批照片沒有冗餘。**

## 提供相機與逐張高度資料後減量

複製並編輯 `config/default.json` 成自己的設定，在 `camera_profiles` 中以 Metadata 的精確型號作為 key。每個 profile 要包含實際感光元件寬高（mm）及匹配的照片寬高（px）。焦距取照片的實際 `FocalLength`，不使用 35mm 等效焦距。禁止使用未查證的相機規格。

高度 CSV 欄位：

```csv
relative_path,agl_m,source,pitch_deg,yaw_deg
flight-a/photo001.jpg,100,survey-derived AGL with compatible vertical datum,-90,0
```

這是格式示例，不是現有照片的真實資料。`relative_path` 必須與輸入資料夾內相對路徑一致，不能重複；`agl_m` 必須為正值；`source` 必填。可只提供部分照片，其餘保留。

可選的 `pitch_deg`／`yaw_deg` 是經確認且標準化的相機角度覆寫：垂直向下 pitch 為 -90°，yaw 為由北順時針的方位角。原始 vendor 欄位仍記錄於 Manifest，覆寫資料檔 SHA-256 保存在 Summary。相對起飛高度不是當地離地高度。

```sh
.venv/bin/uav-optimize ../UserUpload-original \
  --config config/my-camera.json --heights data/heights.csv \
  --min-overlap 0.8 --output outputs/selected-80 --copy
```

`--min-overlap 0.6` 可測試 60% 的最低要求；這是比例值，不接受數字 `60` 或 `80`。候選門檻 `overlap_threshold` 預設維持 0.8，與最低保留要求分別記錄。

## 輸出

| 檔案 | 用途 |
|---|---|
| summary.json | 原始／選取張數、容量、減量比例、原因統計、設定快照、執行版本 |
| manifest.json | 每張照片 Metadata、候選與最終決策、回補及銜接狀態 |
| manifest.csv | 可用試算表開啟的逐張明細，防止檔名被當作公式 |
| selected-files.json | 保留照片相對路徑清單，包含 BYPASS_KEEP |
| selected/ | 僅 `--copy` 建立；保留原本子資料夾結構，避免同名衝突 |
| copy-result.json | 複製完成／失敗狀態；成功時列出複製位元流 SHA-256 |

輸出路徑不得與來源互相包含，也不得覆寫已存在的輸出目錄。複製前後檢查來源大小與修改時間；失敗保留部分輸出並標示 FAILED，可用新輸出目錄重試。不自動清除任何來源或輸出。

## 幾何與版本限制

- 只支援近垂直、局部近似平坦且相機 yaw 接近航向／反航向的情況；其他保守保留。不同 Footprint 長度以區間交集除以較大長度作估算。
- 航帶以時間、相機、GPS 軌跡、角度與高度變化切分；不會跨不可信區段刪照片。未知拍攝時間會保留整個相機資料流。不同設備沒有序號且共用同型號／時間時，應分開執行。
- 局部回補採整段候選保留，可能偏保守。尤其候選門檻及最低要求都為 80% 時，不規則間距可能造成低減量率，並非追求最少照片的全域最佳化。
- **本版未實作跨航帶旁向重疊／全區域覆蓋檢核**，報告明示 NOT_IMPLEMENTED／NOT_EVALUATED。沿同航帶的橫向偏移檢查不能代替旁向覆蓋檢查。
- 未執行 Metashape 建模，也不保證影像內容匹配或模型品質。正式使用前須對代表性資料做原始與減量集合 A/B 建模比較。
- TIFF/DNG 由 ExifTool 擷取 Metadata；不解碼照片像素。掃描採批次執行，單批讀取失敗保留該批，輸出原因。
- 此為獨立 CLI 第一版，未接 Upload／Job／DB，亦非原 UDAS 全規格完成版。設定錯誤在輸出前報錯，來源完整保留；沒有現存 upload 可自動 fallback。

## 測試與專案結構

```sh
.venv/bin/python -m unittest discover -s tests -v
```

```text
uav-photo-optimizer/
├── pyproject.toml
├── requirements.lock
├── config/default.json
├── src/uav_photo_optimizer/  # config / metadata / selection / cli
├── tests/
├── docs/                   # 設計、驗證與版本紀錄
├── .Codex/plans/
└── outputs/                # 本機執行結果，Git 忽略
```

原始照片位於專案外。`data/`、`outputs/`、虛擬環境、照片及 `.env` 都不進 Git。此專案使用本機 Git，沒有建立遠端或推送。
