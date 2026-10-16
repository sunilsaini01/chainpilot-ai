# Datasets

ChainPilot AI uses two public datasets for its machine-learning models and its own synthetic data for operations. **Raw data is never committed to Git** (`data/raw/` is in `.gitignore`).

| Dataset | Used for | Phase | Status |
|---|---|---|---|
| Kaggle **M5 Forecasting – Accuracy** (Walmart) | Demand forecasting | P2 | Downloaded locally by the owner (2026-10-15) and validated |
| Kaggle **Olist Brazilian E-Commerce** | Delivery-delay risk | P3 | Downloaded locally by the owner (2026-10-16) and validated |
| Synthetic operations (`python -m app.cli seed`) | Warehouses, products, stock for the demo | P1 | Done (`SYN-` codes) |

> M5 and Olist describe **different businesses**. Their IDs are never joined as if they were the same company. Each model is evaluated on its own dataset; the dashboard shows their outputs only in a clearly labelled simulated demo scenario.

## M5 Forecasting – Accuracy

Daily unit sales of 3,049 Walmart products in 10 stores (California, Texas, Wisconsin) from 2011-01-29 to 2016-04-24, with a calendar (events, SNAP days) and weekly prices.

Files we use (put them in `data/raw/m5/`):

| File | Contents | Approx. size |
|---|---|---|
| `sales_train_validation.csv` | 30,490 rows (product × store), columns `id, item_id, dept_id, cat_id, store_id, state_id, d_1 … d_1913` | ~120 MB |
| `calendar.csv` | One row per day: `date, wm_yr_wk, weekday, wday, month, year, d, event_name_1/2, event_type_1/2, snap_CA, snap_TX, snap_WI` | ~0.1 MB |
| `sell_prices.csv` | `store_id, item_id, wm_yr_wk, sell_price` (weekly) | ~200 MB |

The download also contains `sales_train_evaluation.csv` and `sample_submission.csv`; they are not needed yet.

### Terms of use

The data is provided under the **competition rules** on Kaggle. You must accept them with your own Kaggle account before you can download, and you should check that they allow your use (here: a non-commercial portfolio/learning project). Do not redistribute the files: this is why they stay out of Git.

### Option A: download in the browser

1. Sign in at https://www.kaggle.com and open https://www.kaggle.com/competitions/m5-forecasting-accuracy/data
2. Accept the competition rules if asked (the **Rules** tab, "I Understand and Accept").
3. Click **Download All** and save `m5-forecasting-accuracy.zip`.
4. Extract the three files above into `C:\projects\chainpilot-ai\data\raw\m5\`. In PowerShell:

   ```powershell
   New-Item -ItemType Directory -Force data\raw\m5
   Expand-Archive "$env:USERPROFILE\Downloads\m5-forecasting-accuracy.zip" -DestinationPath data\raw\m5
   ```

### Option B: Kaggle command-line tool

Needs an API token in `%USERPROFILE%\.kaggle\kaggle.json` (Kaggle → Settings → API → *Create New Token*) **and** the rules accepted in the browser first (step 2 above).

```powershell
pip install kaggle
kaggle competitions download -c m5-forecasting-accuracy -p data\raw\m5
Expand-Archive data\raw\m5\m5-forecasting-accuracy.zip -DestinationPath data\raw\m5
```

Keep `kaggle.json` private: never commit it or paste its contents anywhere.

### Check the download

From the `ml` folder (with the project's Python environment active):

```powershell
cd ml
pip install -r requirements.txt
python -m demand_forecasting.m5_data validate ..\data\raw\m5
python -m demand_forecasting.m5_data validate ..\data\raw\m5 --store CA_1
```

The first command checks all 30,490 series (structure, consecutive days, non-negative whole sales, calendar coverage, prices positive and unique, every series priced) and prints `OK: 30490 series x 1913 days`. The second also prints a summary for one store (rows, dates, share of zero-sales days, share of days without a price). Any problem is printed as `PROBLEM: …` and the command exits with code 1.

### Things to know about M5 (and how the code handles them)

- **Many zeros:** most products sell 0 units on most days. This is why the evaluation uses scale-free metrics (WAPE, RMSSE) instead of percentage errors, which break on zeros.
- **Missing prices** mean the product was not on sale in that store that week (not launched yet). `to_long` leaves `sell_price` empty for those days.
- **SNAP days** differ by state; each series gets its own state's flag (`snap`).
- **Size:** the full table becomes 58.3 million rows when converted to one row per day. Repeated text columns are stored as categories and numbers in small types. Measured on a 16 GB Windows laptop: one store (5.8M rows) takes 179 MB, about 1.2 GB peak while building, in about 10 s; all 10 stores take 1.8 GB, 6.4 GB peak, in about 66 s. Prefer one or a few stores at a time (`store_ids=["CA_1"]`, or `--store CA_1`).
- **No leakage:** prices and the calendar are known in advance, so they may be used as forecast inputs. Lag and rolling features (P2-T2) only use days before the forecast date, and all splits are by time.

### Test fixtures

`ml/tests/fixtures/m5_tiny/` holds three tiny files in the **same format** as M5, with **invented numbers** (6 series × 21 days). They are generated by `ml/tests/fixtures/make_m5_tiny.py` and let the tests and CI run without the real data. They are not M5 data.

### Validation result on the real files (2026-10-15)

```text
> python -m demand_forecasting.m5_data validate ..\data\raw\m5
OK: 30490 series x 1913 days
Summary skipped for this many series; add e.g. --store CA_1 to see one.

> python -m demand_forecasting.m5_data validate ..\data\raw\m5 --store CA_1
OK: 3049 series x 1913 days
  rows: 5832737
  series: 3049
  stores: ['CA_1']
  first_date: 2011-01-29
  last_date: 2016-04-24
  zero_sales_share: 0.639
  days_without_price_share: 0.194
```

In store CA_1, 63.9% of product-days have zero sales, and 19.4% of product-days have no price (product not yet on sale).

## Olist Brazilian E-Commerce

About 99k orders (Sep 2016 to Oct 2018) from Olist, a Brazilian marketplace: orders with purchase, carrier-handover, delivery and promised dates, plus items, products, sellers, customers, payments, reviews and zip-code coordinates. **A different business from M5**: the two datasets are never joined.

Download: https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce (sign in; check the licence shown on the page). Extract the CSV files into `data/raw/olist/`:

```powershell
New-Item -ItemType Directory -Force data\raw\olist
Expand-Archive "$env:USERPROFILE\Downloads\archive.zip" -DestinationPath data\raw\olist
cd ml
python -m delivery_risk.olist_data validate ..\data\raw\olist
```

The loader uses 7 of the 9 files. `olist_order_reviews_dataset.csv` is **deliberately not read** (reviews are written after delivery: leakage), and the category translation file is not needed.

### How the delivery data is prepared (`ml/delivery_risk/olist_data.py`)

- **Label `late`:** delivered to the customer on a calendar day after the promised (estimated) delivery date. 23:30 on the promised day is on time.
- **Prediction point: dispatch**, when the seller hands the order to the carrier. Features use only what is known then: the promise, prices, freight, product size and weight, seller and customer states, the distance between their zip-code centroids, payment, and the dispatch facts (handling time, whether the seller missed its shipping deadline). Never used: the customer delivery date, reviews, the final order status. A test changes every delivery date and checks that no feature moves.
- **Time split by purchase date:** train 2017-01-01..2017-12-31, validation 2018-01-01..2018-03-31, test 2018-04-01..2018-08-31.
- **Dropped, and counted:** not delivered (outcome unknown), missing or impossible dates, purchases outside the split windows, and orders promised within 30 days of the data end (late ones might not have arrived yet, which would make the test period look better than it was).

### Validation result on the real files (2026-10-16)

```text
OK: 99441 raw orders -> 95723 usable delivered orders
  dropped   2963: not delivered (outcome unknown)
  dropped      9: missing delivery or carrier date
  dropped    188: inconsistent dates (handover before purchase, or delivery before handover)
  dropped    295: promised date within 30 days of the data end (outcome may be censored)
  dropped    263: purchased outside the split windows (2016, Sep-Oct 2018)
  train       43406 orders 2017-01-01..2017-12-31, late rate 0.056
  validation  20627 orders 2018-01-01..2018-03-31, late rate 0.129
  test        31690 orders 2018-04-01..2018-08-31
```

The test late rate is not shown on purpose: it is looked at once, in the final evaluation. Note the jump from 5.6% (2017) to 12.9% (early 2018): conditions changed, so calibration must be checked on recent data (P3-T2).

Fixtures: `ml/tests/fixtures/olist_tiny/` holds 10 hand-written orders in the Olist format (one per edge case), generated by `make_olist_tiny.py`. They are not real Olist data.
