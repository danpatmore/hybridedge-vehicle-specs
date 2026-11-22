# Vehicle database sweep, 22 Nov 2026

First scheduled sweep. Window: 10 Nov 2026 (the `vehicles` date in `checks/last-checked.json` and the newest report, `Vehicle-Sweep-2026-11-10.md`) to 22 Nov 2026, plus that report's open items. Starting point: car list v1.34.1, 145 rows.

**How it was done.** About 15 web searches and page reads, press first where makers' AU pages give nothing (GWM's H7 page was read and still gives no charging rate). "Single" means one outlet only; "snippet" means a search result summary, page not read. BOC = before on-road costs, d/a = drive-away.

## What changed (car list v1.34.2)

- **GWM Haval H7 PHEV AWD (Lux / Vanta), 2027:** `acChargerKW` 6.6 (was blank), `acChargerPhases` 1, `estimatedHomeChargeHours` 5.1 (33.7 kWh / 6.6 kW, the file's usual working). Three outlets agree: EV Central's H7 spec page, updated 21 Nov [1]; CarExpert's review, 10 Nov, from JATO Dynamics data and given for the whole H7 range [2]; carsales' Vanta PHEV review (snippet, 403) [3]. GWM AU still publishes no charging rate [4]. The DC rate stays blank: 85 kW appears only in CarExpert's JATO table [2], and a South African review measured 75 kW peak [5]. The row was missing only the AC rating and engine cc, so builds before 242 still skip it (engine cc is still unpublished).

## 1. Ready to add

None.

## 2. On sale or priced, but held

| Model | Why held | What was found |
|---|---|---|
| **Chery Stockman** (diesel PHEV dual-cab; Urban, Ultimate) | Now priced, but pre-launch: deliveries from 1 Feb 2027, tuning still under way, payload still being worked on, and the protocol says pre-launch cars wait for AU launch. The 10 Nov report said "add once priced", which conflicts with that rule, so it is left for the developer's ruling. Also missing: AC and DC rates (not in CarExpert's pricing article), engine cc | Urban $52,990, Ultimate $57,990 BOC [6][7]; 34 kWh LFP; 100 km WLTP (96 km on all-terrain tyres); 1.0 to 1.1 L/100km claimed; 80 L; 3,495 kg braked; kerb 2,690 to 2,735 kg; 2.5 turbo-diesel four, 350 kW / 800 Nm [6]. 1 Oct–10 Nov figures (6.6 kW AC, 70 kW DC, 8 yrs / unlimited km battery) are from Chery's indicative spec, not re-confirmed |
| **GWM Cannon Hi4-T** (Lux, Ultra), 2027 row already in the file with AC blank | AC rating: no source for the Hi4-T itself. The 6.6 kW found is from CarExpert's spec tables for the Cannon Alpha and Tank 500 Hi4-T [8], which are other cars | No change |
| **BYD M9 Dynamic** | AC rating and EV range still unpublished by BYD; EV Central's "80 km" is unsourced [9] | Unchanged: $61,990 BOC, 20.39 kWh, arriving later |
| **Mercedes GLE 450e**, **AMG E 53 / C 63 S E / GLC 63 S E / GT 63 S E**, **Bentley**, **Ferrari**, **McLaren** | Unchanged from the 10 Nov report (in the file since v1.33.0 / v1.34.0 with blanks: chemistry, battery warranty, AC where noted). Not re-researched this run | — |
| **Audi A6 allroad e-hybrid** | Not here until H1 2027; chemistry still missing | — |

## 3. Rows already in the file

- **XPeng L03 Power-X:** no report of first AU deliveries yet; RACV still says "expected before the end of this year" [10]. Row stays as is.
- No corrections found this run. The 10 Nov corrections (RAV4 121 km / 144 km NEDC, Tiggo 7 and J7 at 18.4 kWh) are already in the file.

## 4. Coming

- **Chery Stockman:** see section 2.
- **GWM Wey G9:** approved, still unpriced; carsales now says the full Wey roll-out slips to 2027, with perhaps a price announcement this year [11].
- **Haval Jolion Max PHEV:** early 2027, unpriced [12].
- **VW Transporter eHybrid:** delayed, still unpriced [13].
- **BYD Ti7:** BYD Australia told CarsGuide it "isn't currently on its radar" [14] (10 Nov report had approval documents and H1 2027).
- **Omoda 7 SHS:** still slipped, unpriced.
- Everything else on the 10 Nov list: nothing new found in this window.

## 5. Completeness check

No newer per-model list than Drive's H1 2026 FCAI table (see the 10 Nov report); October VFACTS is still reported as totals only. Nothing new to compare.

## Sources (read 22 Nov 2026 unless dated)

1. https://evcentral.com.au/cars/gwm/haval-h7/ (updated 21 Nov 2026)
2. https://www.carexpert.com.au/car-reviews/2027-gwm-haval-h7-review (10 Nov 2026)
3. https://www.carsales.com.au/editorial/details/gwm-haval-h7-vanta-phev-awd-2027-review-153508/ (403; snippet)
4. https://www.gwmanz.com/au/models/suv/haval-h7/
5. https://www.cars.co.za/motoring-news/haval-h7-phev-2026-review/364314/ (snippet)
6. https://www.carexpert.com.au/car-news/2027-chery-stockman-pricing-diesel-phev-ute-undercuts-byd-shark-6 (Fri 20 Nov 2026)
7. https://www.carsales.com.au/editorial/details/chery-stockman-australia-pricing-announced-153544/ (snippet)
8. https://www.carexpert.com.au/car-reviews/2025-gwm-cannon-alpha-hi4-t-phev-review and https://www.carexpert.com.au/car-reviews/2025-gwm-tank-500-hi4-t-phev-review (snippets)
9. https://evcentral.com.au/cars/byd/m9/ and https://zecar.com/reviews/byd-m9-price-specs-australia (snippets)
10. https://racv.com.au/royalauto/transport/electric-vehicles/2027-xpeng-l03-price-specs-release-date.html (snippet)
11. https://www.carsales.com.au/editorial/details/wey-delay-chinese-premium-brand-wont-get-up-and-rolling-till-2027-153528/ (snippet)
12. https://evcentral.com.au/gwms-first-electric-haval-revealed-jolion-max-ev-and-phev-confirmed-for-australia-as-chinese-brand-targets-suv-domination/ (snippet)
13. https://www.carexpert.com.au/car-news/volkswagen-transporter-ev-arrives-but-phev-delayed (snippet)
14. https://www.carsguide.com.au/car-news/byd-reveals-prices-for-new-2027-byd-ti7-large-plug-in-hybrid-suv-in-the-uk-but-still-no (snippet)
