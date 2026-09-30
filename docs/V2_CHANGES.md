# BrandGuard v2 — değişen ve eklenen dosyalar

Zip (`brandguard-v2.zip`) repo'nun tam halidir; `web/node_modules`, `web/dist`
ve `data/brandguard.db` içinde yoktur (çalıştırınca oluşur).

## Elle yerleştirmek istersen: konum listesi

### Yeni dosyalar
| Dosya | Ne |
|---|---|
| `src/brandguard/config.py` | `.env` repo kökünden okunur; DB ve veri yolu ayarları |
| `src/brandguard/product/__init__.py`, `category.py`, `resolve.py` | Kategori eşlemesi (K-057), girdi çözümleme (K-060) |
| `src/brandguard/api/__init__.py`, `__main__.py`, `db.py`, `models.py`, `schemas.py`, `brands.py`, `scan_service.py`, `worker.py`, `main.py` | Ürün API'si (K-059) |
| `tests/test_hardening.py`, `tests/test_api.py`, `tests/test_resolve.py` | 50 yeni test |
| `scripts/legacy/` (+ `README.md`, `__init__.py`) | Eski tek kaynaklı scriptler buraya taşındı |
| `web/` (tümü) | React arayüzü |
| `Dockerfile`, `docker-compose.yml`, `.dockerignore` | Paketleme |

### Değişen dosyalar
| Dosya | Değişiklik |
|---|---|
| `src/brandguard/discovery/normalize.py` | İ bug'ı: Türkçe katlama `lower()`'dan önce |
| `src/brandguard/discovery/parsing.py` | `1.000+` / `1,5M` biçimleri; bool tarih koruması |
| `src/brandguard/discovery/serper_source.py` | 11 APK host, sayfalama, `gl/hl`, sayfa türü filtresi, hata toplama |
| `src/brandguard/discovery/live_google_play.py` | Detay önbelleği, `skip_ids`, istek aralığı, `appId=None` atlanır |
| `src/brandguard/discovery/query_expansion.py` | `select_queries()`: bütçe stratejilere dağıtılır |
| `src/brandguard/discovery/website_hunt.py` | Aramada bulunan üretilmiş varyant canlıya yükseltilir; import düzeni |
| `src/brandguard/discovery/domain_variants.py` | Tuzak kelime listesi sınıflandırıcıyla hizalandı |
| `src/brandguard/triage/adjudicator.py` | Güvenli JSON parse, 30 sn timeout, config loader |
| `src/brandguard/triage/tier2.py` | Hakem erişilemezse tarama düşmez |
| `src/brandguard/triage/fusion.py` | Çelişki listesi sinyal adlarıyla (ham isim LLM'e gitmez) |
| `src/brandguard/hunt_engine.py` | `DEFAULTS`, zengin satırlar (score/tiers/reason/category), hata+uyarı+süre, K-056 alarmı, non-listing → noise |
| `src/brandguard/hunt.py`, `registry.py` | Küçük: docstring, dotenv config'e bağlandı |
| `tests/test_provider_selection.py`, `test_registry.py`, `test_watchlist.py`, `test_live_adapter.py` | Yeni davranışa/yola uyarlandı |
| `pyproject.toml` | `api` ve `all` extra'ları |
| `.gitignore`, `.env.example`, `README.md`, `KARARLAR.md` (K-057…K-061) | Dokümantasyon |

## v2.1 — ilk canlı taramadan sonra (K-062…K-064)

### Yeni
| Dosya | Ne |
|---|---|
| `src/brandguard/product/affiliate.py` | "Olası iştirak" ipucu (K-063) |
| `web/src/explain.ts` | Kanıtların ve karar yolunun sade dille anlatımı |
| `tests/test_v2_fixes.py` | 11 test: Serper None bütçesi, geliştirici hesabı, iştirak, Play no-result |

### Değişen
| Dosya | Değişiklik |
|---|---|
| `src/brandguard/hunt_engine.py` | APK kaynağı `max_queries=None` çökmesi düzeltildi; ikinci geçiş: aynı Play geliştirici hesabı → resmi (K-062); iştirak ipucu; satırlara `facts` (yayıncı, site, kurulum, tarih) |
| `src/brandguard/schema.py` | `Publisher.account_id` |
| `src/brandguard/discovery/live_google_play.py` | `developerId` → `account_id` |
| `src/brandguard/discovery/play_search.py` | "Sonuç yok" sayfasındaki TypeError boş sonuç sayılır (K-064) |
| `src/brandguard/product/category.py` | `Category.AFFILIATE`, `app_category(affiliate_hint=)` |
| `src/brandguard/api/scan_service.py` | `facts` → `Finding.extra` |
| `web/src/api.ts`, `index.css` | `affiliate` kategorisi, `CATEGORY_HINT`, renk token'ları |
| `web/src/components/DetailsDrawer.tsx` | Yeniden yazıldı: "Kısaca" özeti, yayıncı/kurulum/site kartı, artı/eksi/kesin gruplu kanıtlar, teknik metni göster/gizle, "profile ekle" düğmesi |
| `web/src/components/FindingsTable.tsx`, `Counters.tsx`, `pages/ScanPage.tsx`, `pages/BrandPage.tsx` | Sade kanıt satırı, sekme ipuçları, drawer'a marka aktarımı |
| `KARARLAR.md`, `README.md` | K-062, K-063, K-064 |

## v2.2 — ikinci canlı tur (K-065, K-066, arayüz tek dil)

### Yeni
| Dosya | Ne |
|---|---|
| `web/src/components/Explanation.tsx` | Ortak "neden" paneli: özet, yayıncı/kurulum kartı, artı/eksi/kesin gruplu kanıtlar, karar yolu, "add to profile" |

### Değişen
| Dosya | Değişiklik |
|---|---|
| `src/brandguard/triage/veto.py` | Mod/crack vetosu yalnızca markayla ilişkili ilanlarda (K-065) |
| `src/brandguard/registry.py` | `identity_tokens()`, `names_identity()`; `_is_brand_site(host, brand)` platformun kendi alan adını kabul eder (K-066) |
| `src/brandguard/product/resolve.py` | Paket yolu listing başlığı/geliştiriciyi marka ipucu olarak geçirir |
| `src/brandguard/product/affiliate.py` | Ortak kimlik token'larını kullanır |
| `src/brandguard/hunt_engine.py` | Play: resmi paket kimlikleri doğrudan çekilir; K-056 alarmı yalnızca aramaya bakar |
| `src/brandguard/discovery/live_google_play.py` | `search_and_fetch(seen_out=)` |
| `src/brandguard/api/main.py` | `DELETE /api/brands/{id}` (taramalar ve bulgular dahil; çalışan tarama varsa 409) |
| `web/src/**` | Arayüz tamamen İngilizce; tabloda satır başına ▾ "why" paneli; tarama sürerken "Scanning…" boş durumu; mavi "Running" rozeti; Brands sayfasında Delete |
| `tests/test_unauthorized_build.py`, `tests/test_v2_fixes.py`, `tests/test_api.py` | Yeni davranışlar (305 test) |
| `KARARLAR.md`, `README.md` | K-065, K-066 |
| `src/brandguard/api/scan_service.py` | Alan adı bulunamamış otomatik profil bir sonraki taramada yeniden çözümlenir ve yerinde yükseltilir (TikTok'un "saved profile used" sorunu) |
| `src/brandguard/api/main.py` | `GET /api/scans/{id}/export` — tarama + marka + tüm bulgular tek JSON; arayüzde "Export JSON" düğmesi. `BRANDGUARD_BASIC_AUTH=user:pass` ile isteğe bağlı giriş kapısı (tünel/LAN demoları için) |
| `.env.example`, `README.md` | `BRANDGUARD_BASIC_AUTH`; "demo / dışarı açma" notu |

## v2.4 — 13 canlı export'un analizi (K-068, K-069)

| Dosya | Değişiklik |
|---|---|
| `src/brandguard/triage/veto.py` | `companion_marker()`: "X for Brand (MOD)", "download brand video", downloader/stats/tips/guide… → veto susar (K-068) |
| `src/brandguard/triage/scored_signals.py` | `companion_build_signal` (nötr): nedeni kanıta yazar |
| `src/brandguard/product/resolve.py` | Play developer URL → marka adı girdisi; mağaza/platform alan adları reddedilir (K-069) |
| `src/brandguard/discovery/serper_source.py` | sikayetvar, eksisozluk, xdaforums, forum./community./github… → article |
| `web/src/explain.ts` | companion_build açıklaması; related özetinde "not a takedown" cümlesi |
| `tests/test_v2_fixes.py` | 5 yeni test (313) |
| `KARARLAR.md` | K-068, K-069 |

Export'ların yeniden oynatılması (K-065+K-068): malicious 163 → 72; kalan her satır markanın kendi ürününü adlandırıyor.

## v2.5 — Pegasus örneği (K-070)

| Dosya | Değişiklik |
|---|---|
| `src/brandguard/triage/adjudicator.py` | Açıklama olgularında uygulamanın kendi adı marka anması sayılmaz; "official" iddiası marka anmasının 80 karakter yakınında olmalı; kural hakemine "namesake" kuralı; model prompt'una not |
| `src/brandguard/discovery/serper_source.py` | `mitre.org` article host |
| `tests/test_v2_fixes.py` | +1 test (314) |
| `KARARLAR.md` | K-070 |

Arayüz değişmedi; `npm run build` gerekmez.

## v2.6 — Pegasus, ikinci tur (K-071)

| Dosya | Değişiklik |
|---|---|
| `src/brandguard/hunt_engine.py` | `identity_terms()` (yayıncı + amiral uygulama başlığı sorgulara eklenir); `soften_ambiguous_mods()` (belirsiz marka kelimesi → uncertain) |
| `src/brandguard/triage/veto.py` | Edat penceresi 3 kelime ("for asus pegasus 5000") |
| `src/brandguard/discovery/serper_source.py` | `search_apks(extra_terms=)` |
| `web/src/explain.ts`, `api.ts` | `ambiguous_brand_word` açıklaması |
| `tests/test_v2_fixes.py` | +5 test (319) |
| `KARARLAR.md` | K-071 |

**Bundan sonra zip'ten `src/` klasörünü komple değiştir** (içinde kullanıcı verisi yok); tek tek dosya seçmek eski sürüm parçası bırakıyor. `web/src` de değişti → Docker: `docker compose up --build -d`.

## v2.7 — 16 markalık ikinci canlı tur (K-072)

| Dosya | Değişiklik |
|---|---|
| `src/brandguard/registry.py` | Sektör kelimeleri generic listesine (kredi, telekom, finans…); `clean_brand_name()` yasal ekleri atar |
| `src/brandguard/product/resolve.py` | Yayıncı adından marka adı üretilirken yasal ek temizlenir |
| `src/brandguard/api/scan_service.py` | Platform alan adı reddi kayıtlı marka aramasından önce (bayat "Google LLC" satırı) |
| `src/brandguard/hunt_engine.py` | Resmi alan adındaki sayfa → noise; K-071 kapatma anahtarı markanın herhangi bir kelimesi = alan adı etiketi |
| `src/brandguard/discovery/play_search.py`, `serper_source.py` | Play no-result KeyError; fintables/scribd/archive.org article |
| `src/brandguard/api/main.py` | Export dosya adı ASCII (Türkçe harf başlığı kırıyordu) |
| `web/src/pages/ScanPage.tsx`, `api.ts`, `explain.ts` | Export düğmesi hatayı gösterir; yeni reason metni |
| `tests/` | 325 test |
| `KARARLAR.md` | K-072 |

Brands sayfasından eski **Google LLC** kaydını silin.

## v2.8 — toplu tarama

| Dosya | Değişiklik |
|---|---|
| `src/brandguard/api/models.py`, `db.py` | `Scan.batch_id`; mevcut DB'ye kolon ekleyen küçük migrasyon (DB silmeye gerek yok) |
| `src/brandguard/api/schemas.py`, `scan_service.py`, `main.py` | `POST /api/scans/batch` (satır başına bir tarama; hatalı satırlar rapor edilir, diğerleri çalışır), `GET /api/batches/{id}`, `GET /api/scans?batch_id=` |
| `web/src/pages/StartPage.tsx` | "Multiple brands" düğmesi → çok satırlı giriş; birden çok satır yapıştırınca otomatik |
| `web/src/pages/BatchPage.tsx` (yeni), `App.tsx`, `ScansPage.tsx`, `api.ts` | Toplu tarama sayfası: toplam sayaçlar, marka başına durum/sonuç, taranamayan girdiler |
| `src/brandguard/api/main.py` | `GET /api/batches/{id}/export` — ZIP: marka başına bir JSON + `summary.json` |
| `web/src/pages/BatchPage.tsx`, `api.ts` | "Export all (ZIP)" ve satır başına "JSON"; ortak `downloadFile()` (hata görünür) |
| `src/brandguard/api/scan_service.py`, `main.py` | İptal: `POST /api/scans/{id}/cancel`, `POST /api/batches/{id}/cancel`; kuyruktaki kaynaklar çalışmaz, biten kaynakların bulguları kalır |
| `web/src/pages/ScanPage.tsx`, `BatchPage.tsx`, `ui.tsx`, `SourceStrip.tsx` | "Cancel" / "Cancel remaining" düğmeleri, `cancelled` durumu |
| `tests/test_api.py` | +5 test (330) |

## v3.0 — analist kararları, fark görünümü, zamanlanmış tarama (K-073)

| Dosya | Değişiklik |
|---|---|
| `src/brandguard/api/models.py`, `db.py` | `reviews` tablosu; `Scan.trigger`; `Brand.schedule/schedule_sources/schedule_depth/next_run_at` (mevcut DB'ye otomatik eklenir) |
| `src/brandguard/api/scan_service.py` | `set_review/clear_review/reviews_for`, `needs_action_count`, `previous_scan/diff_scans`, `set_schedule/run_due_schedules` |
| `src/brandguard/api/main.py` | `PUT/DELETE /api/brands/{id}/reviews/{key}`, `GET …/reviews`, `GET /api/scans/{id}/diff`, `items?new_only&open_only`, `counts.needs_action`, PATCH brand schedule alanları, zamanlayıcı thread'i |
| `web/src/components/ReviewPanel.tsx` (yeni) | Kararlar: Confirmed / Takedown sent / False positive / Resolved + not; tabloda rozet |
| `web/src/pages/ScanPage.tsx` | "Needs action" kararları düşer; "New" sekmesi; "Since the previous scan" satırı (gone/changed detayı) |
| `web/src/pages/BrandPage.tsx` | "Scheduled re-scan" paneli (Off/Daily/Weekly, kaynaklar, derinlik, sonraki çalışma) |
| `web/src/pages/ScansPage.tsx` | "scheduled" işareti |
| `tests/test_api.py` | +4 test (334) |
| `KARARLAR.md` | K-073 |

## v3.1 — 20 markalık üçüncü tur (K-074, K-075)

| Dosya | Değişiklik |
|---|---|
| `src/brandguard/product/affiliate.py`, `category.py`, `hunt_engine.py` | Yalnız kelimelerle belirsiz kalan marka-adlı yayıncı → Affiliate? (K-074) |
| `src/brandguard/registry.py` | Üç harfli markalar (QNB, n11) kimlik tokeni; kısa token tam kelime eşleşir |
| `src/brandguard/schema.py`, `hunt_engine.py`, `api/scan_service.py` | Play, marka kelimesini kaç adaş yayıncının kullandığını ölçer (`measurements`); APK-site koşusu Play'i bekleyip okur (K-075) |
| `src/brandguard/product/resolve.py` | Alan adı etiketi Play'de sonuç vermezse sayfa başlığıyla ikinci arama (turkishairlines.com) |
| `src/brandguard/triage/veto.py` | katalog/catalog/brosur/aktuel companion kelimeleri |
| `src/brandguard/hunt_engine.py` | Mirror sitelerdeki resmi uygulama kopyaları: `mirror_listing` kanıtı, `mirror_unverified` gerekçesi |
| `web/src/explain.ts`, `api.ts` | Yeni gerekçe metinleri |
| `tests/` | 341 test |
| `src/brandguard/discovery/serper_source.py`, `hunt_engine.py` | Paylaşılan marka kelimesinde APK sorguları kimlik kelimesiyle çapalanır; mod sorgusu ikinci sıraya (K-076) |
| `KARARLAR.md` | K-074, K-075, K-076 |

## v3.3 — üç alanlı girdi, arayüz düzenlemesi (K-077)

Bu sürümden itibaren en kolayı: zip'teki `src/` ve `web/src` klasörlerini olduğu gibi
üstüne yazmak (tek tek dosya yerine). Ardından `docker compose up --build -d`.

| Dosya | Değişiklik |
|---|---|
| `src/brandguard/api/scan_service.py` | `resolve_structured(name, domain, store)`: üç alandan profil; var olan markaya eklenir (`existing+merged`); yazılan ad "guessed from the domain label" notunu kaldırır |
| `src/brandguard/api/schemas.py`, `main.py` | `ScanRequest.brand_name/domain/store`; toplu satırlar `Ad | alanadi | link` |
| `src/brandguard/triage/veto.py` | Play'de resmi paket id'si tek başına kimliktir: yayıncı adı profilde yoksa bile Official (metin "add it to the profile" der); paket vetosu Play'de resmi id için artık çalışmaz, mirror'larda çalışır (K-077) |
| `web/src/pages/StartPage.tsx` | "One brand / Several brands" anahtarı formun tepesinde; üç etiketli alan (Brand name / Official domain / Google Play link), alan doğrulama ve ipucu; kaynak/derinlik kartları |
| `web/src/ui.tsx` | `Segmented` bileşeni |
| `web/src/index.css` | `.segmented`, `.option`, `.btn-danger`, `.btn-ghost`, `.btn-link`, `.icon-btn`, `.progress`; `--on-accent`; `[data-theme]` ile açık/koyu tema |
| `web/src/Layout.tsx` | Tema düğmesi (açık/koyu, tarayıcıda hatırlanır); sağlık çipleri (Adjudicator, APK sites) açıklamalı; "N running" rozeti; menü "New scan" |
| `web/src/components/FindingsTable.tsx` | Ok yerine görünür "Why?" ve "Details" düğmeleri |
| `web/src/pages/ScansPage.tsx` | Filtre (All / Running / Needs attention / In a batch) + arama kutusu; satırda Cancel / Open |
| `web/src/pages/BrandsPage.tsx` | Satırda "Scan now" (kayıtlı profille) ve kırmızı Delete; Re-scan sütunu |
| `web/src/pages/BatchPage.tsx` | İlerleme çubuğu; Export JSON / Open düğmeleri; kırmızı "Cancel remaining" |
| `web/src/pages/ScanPage.tsx` | Kırmızı "Cancel scan"; "Scan again" birincil düğme |
| `web/src/pages/BrandPage.tsx` | Zamanlama Off/Daily/Weekly segment kontrolü |
| `web/src/api.ts` | `createScan` üç alanı kabul eder |
| `tests/test_api.py`, `tests/test_veto_claimed_website.py` | +2 test (345) |
| `KARARLAR.md` | K-077 |

## v3.4 — sayfalı tarama listesi, tarama silme

| Dosya | Değişiklik |
|---|---|
| `src/brandguard/api/main.py`, `schemas.py` | `GET /api/scans/search?q=&view=all|active|attention|batches&limit=50&offset=` sayfalı liste (`ScanPage`); `DELETE /api/scans/{id}` (çalışırken 409; marka ve analist kararları kalır) |
| `web/src/pages/ScansPage.tsx` | Sayfa başına 50 kayıt, alt kısımda 1 2 3 … sayfalama; filtre ve arama sunucuda, URL'de saklanır; satırda Delete (bitmiş) / Cancel (çalışan) |
| `web/src/pages/ScanPage.tsx` | Başlıkta Delete düğmesi |
| `web/src/api.ts` | `searchScans`, `deleteScan` |
| `web/src/index.css` | Örnek metinler (placeholder) daha silik |
| `tests/test_api.py` | +1 test (346) |

## v3.5 — metin okuyan T2 (K-078)

| Dosya | Değişiklik |
|---|---|
| `src/brandguard/triage/reader.py` (yeni) | `CaseText` (sınırlı, temizlenmiş metin), rastgele etiketli veri bloğu ile prompt, enum-doğrulamalı `parse_reading` (alıntı metinde geçmeli, not URL'siz ve talimat değilse), `derive_leaning` (karar kodda), `reading_evidence`, SQLite `ReadingCache` |
| `src/brandguard/triage/adjudicator.py` | `LLMAdjudicator.read(case, text)`; Anthropic/OpenAI aynı taşıma; `BRANDGUARD_LLM_MODEL`; `describe_adjudicator()`; `stats` (çağrı / önbellek / hata / enjeksiyon); `CaseSummary.publisher_official` |
| `src/brandguard/triage/tier2.py` | Okuyucu varsa onu kullanır; okuma satırları bulguya eklenir; T0'ın yükseltmediği "uncertain" kayıtlar da T2'ye gider |
| `src/brandguard/hunt_engine.py` | Bulgu `facts`: `description_excerpt` (600), `permissions`, `account_created`, `other_app_count`, `verified`; kaynak notu "T2: N listing(s) read…" |
| `src/brandguard/api/main.py`, `schemas.py` | Health: `adjudicator_model` |
| `scripts/replay_t2.py` (yeni) | Export'ları kuralla ve modelle yeniden koşar, kategori değişimlerini ve okuyucu satırlarını yazdırır |
| `web/src/explain.ts`, `components/Explanation.tsx`, `FindingsTable.tsx`, `Layout.tsx`, `api.ts` | "What the listing text says" grubu; "Listing text (untrusted)" açılır kutusu; başlıkta Reader çipi model adıyla; "T2 · text reader" |
| `.env.example`, `.gitignore`, `README.md`, `docs/THREAT_MODEL.md` | Yeni ayarlar ve enjeksiyon savunmasının açıklaması |
| `tests/test_reader.py` (yeni) | 14 test: sınırlama, etiketleme, enum doğrulama, uydurma alıntı, talimat notu, enjeksiyon çökmesi, çelişki, karar dalları, kaskad, önbellek |
| `KARARLAR.md` | K-078 |

Notlar: değerlendirme seti çıktısı değişmedi (kural adjudicator ile). Model anahtarı olan makinede
`python scripts/replay_t2.py <export.json> --only-changed` ile eski export'lar üzerinde kural / model farkı
ölçülür; v3.5 öncesi export'larda açıklama metni olmadığı için o satırlar boş metinle koşar.

## v3.6 — TikTok canlı okuma sonrası düzeltmeler, App Store, sunucu kurulumu (K-079)

| Dosya | Değişiklik |
|---|---|
| `src/brandguard/triage/reader.py` | Yeni konu `brand_app` (markanın uygulamasının kopyası); "namesake" cevabı metin markayı anlatıyorsa ya da başlık resmi uygulama adını taşıyorsa düzeltilir; enjeksiyon raporu yalnızca metin okuyucuya hitap ediyorsa kabul edilir (`reader_directed`, TR/EN); makine okunur `reader_answers` satırı |
| `src/brandguard/hunt_engine.py` | `is_mirror_listing` / `mirror_decision`: mirror kopyaları T2'ye gitmez, benign'e kapanmaz, güven 0.25; App Store zenginleştirme `_run_serper` içinde (`BRANDGUARD_APP_STORE=0` kapatır); `facts.page_kind`, `facts.bundle_id` |
| `src/brandguard/discovery/app_store.py` (yeni) | iTunes Lookup ile apps.apple.com isabetleri satıcı, site, bundle id, açıklama ile gerçek listeye dönüşür |
| `src/brandguard/triage/veto.py` | `app_store` tekil-id mağaza; resmi bundle id kimlik kanıtı |
| `deploy/docker-compose.prod.yml`, `deploy/Caddyfile`, `docs/DEPLOY.md` (yeni) | Sunucuda HTTPS'li kurulum (Caddy + sslip.io), 20 dakikalık rehber; tünel yerine |
| `scripts/replay_t2.py` | page_kind ve bundle_id ile sadık replay |
| `web/src/components/FindingsTable.tsx` | "App Store" kaynak adı |
| `tests/test_reader.py` | +6 test (366) |
| `KARARLAR.md` | K-079 |

## v3.7 — tünel yan konteyneri, başlıkta herkese açık link

| Dosya | Değişiklik |
|---|---|
| `docker-compose.yml` | `cloudflared` servisi (`--profile tunnel`): IPv4 + http2, Docker ile yeniden başlar, pencere gerekmez; metrics 127.0.0.1:2000 |
| `src/brandguard/api/main.py`, `schemas.py` | `public_url()` — tünelin `/quicktunnel` adresinden o anki https adresi (30 s önbellek, hata durumunda boş); health'e `public_url` |
| `web/src/Layout.tsx`, `api.ts` | Başlıkta yeşil "…trycloudflare.com · copy" çipi |
| `docs/RUNBOOK.md` | B bölümü yeniden: `docker compose --profile tunnel up --build -d`, telefondan test, durdur/başlat, hata sayfası ne demek |
| `docs/DEPLOY.md` | Sunucu kurulumu artık isteğe bağlı olarak işaretli |
| `tests/test_api.py` | +1 test (367) |
| `web/src/pages/StartPage.tsx` | "Scan again": önceki girdi üç alana ayrılarak geri gelir (ad / alan adı / Play linki) |

Bu sürümde `docker-compose.yml` dosyasını da zip'ten üstüne yazın.

## v3.8 — üç markalı canlı tur sonrası (K-080)

| Dosya | Değişiklik |
|---|---|
| `src/brandguard/triage/veto.py`, `registry.py` | Yayıncı adı yasal ekiyle/eksiz eşleşir (`publisher_name_matches`: "Spotify" = "Spotify AB"); AB/Oy/AS ekleri |
| `src/brandguard/triage/adjudicator.py` | Resmi alan adındaki site okuyucu için kimlik sayılır (`website_official`) |
| `src/brandguard/hunt_engine.py` | Mirror tespiti T0'dan sonra her veto-dışı sonuçta; başlık "kalıntı" kuralı + yan-uygulama dışlaması; okuyucunun `brand_app` dediği bilinmeyen siteler de `mirror_unverified`; çift satır yok; kategori kelimeleri |
| `src/brandguard/triage/reader.py` | "unrelated" + markayı anıyor → unclear; not istemi: resmi/güvenli yorumu yok; PROMPT_VERSION r2 (önbellek yenilenir) |
| `src/brandguard/discovery/app_store.py` | Yalnız /app/ sayfaları; ad yedeği |
| `src/brandguard/discovery/serper_source.py` | /review/, review-of-, /alternatives, /tag/ sayfaları makale |
| `src/brandguard/product/affiliate.py` | Yan-uygulama adlı ("Notify for Spotify") uygulama Affiliate? olmaz |
| `web/src/pages/ScanPage.tsx` | "Hide mirror copies (N)" anahtarı (tarayıcıda hatırlanır) |
| `tests/test_reader.py` | +7 test (374) |
| `KARARLAR.md` | K-080 |

## v3.9 — Wise turu: paylaşılan marka kelimesi okuyucuyla ölçülür; Trendyol satırı (K-081)

| Dosya | Değişiklik |
|---|---|
| `src/brandguard/hunt_engine.py` | `reader_namesakes`: Play'de okuyucunun "adaş, marka anılmıyor" dediği yayıncı sayısı → `brand_word_shared_by`; `read_softened_mods`: kelime paylaşılıyorsa mod'lar okunur (adaş → noise, markanın uygulaması → takedown); paylaşılan kelimede çıplak-kelimeli mirror sayfası yalnızca resmi uygulama adı/paket id varsa kopya; resmi uygulamaların İngilizce adları çekilir (`official_titles`); kalıntı eşiği 2 harf |
| `src/brandguard/api/scan_service.py` | Alan adına benzeyen mağaza alanı ("trendyol.com") Play'de paket id olarak denenir; İngilizce adlar APK-site koşusuna aktarılır |
| `src/brandguard/api/models.py`, `main.py` | `batches` tablosu: hata satırları kalıcı (sayfa yenilense de, ZIP'te de) |
| `src/brandguard/triage/reader.py` | marka anılmıyorsa kimlik bilgisi iddiası düşer |
| `src/brandguard/product/affiliate.py` | okuyucu "marka anılmıyor" dediyse Affiliate? yok |
| `src/brandguard/triage/adjudicator.py` | resmi uygulama adı tam başlıkla da eşleşir ("Wise: International Transfers") |
| `tests/` | +4 test (378) |
| `KARARLAR.md` | K-081 |

Beklenen etki (Wise): 8 yanlış malicious → 0-1, 10 Affiliate? → 0, mirror kopyası sayısı düşer (adaş uygulamalar okuyucuya gider).

## v3.9.1 — Wise/Trendyol doğrulama turu sonrası

| Dosya | Değişiklik |
|---|---|
| `src/brandguard/registry.py`, `hunt_engine.py` | Çok kelimeli, marka kelimesi taşımayan uygulama adları ("Currency Converter", "Para Birimi Dönüştürücü") kimlik tokeni vermez → yabancı bir converter mod'u Wise'ın takedown'ı olmaz; APK-site çapası artık "birimi" değil "payments" |
| `src/brandguard/discovery/app_store.py` | Apple `artistId` → `account_id`; aynı-hesap kuralı App Store'da da çalışır ("Trendyol: Online Shopping" iOS, Seller Center ile aynı hesap → Official) |
| `src/brandguard/discovery/serper_source.py` | `/developer/` sayfaları listing değil (App Store, apkpure, apkmirror kataloğu) |
| `src/brandguard/triage/reader.py`, `adjudicator.py` | Adı marka kelimesi taşıyan yayıncı ("Trendyol Go") markanın servisini sunuyorsa "impersonation" eğilimi yok; iştirak/impostor kararı doğrulayıcıya/analiste |
| `src/brandguard/product/affiliate.py` | Kelime paylaşılıyorsa yalnız isim tokenine dayanan Affiliate? ipucu yok (ConnectWise, Workwise) |
| `tests/` | +4 test (382) |

## v3.10 — telefon ve tablet düzeni

| Dosya | Değişiklik |
|---|---|
| `web/src/index.css` | Duyarlı sınıflar: `.layout-start/.layout-brand` (≤1024px tek sütun), `.grid-2/3/4` (≤640px tek sütun), `.grid-counters` (telefonda 3'lü), `.grid-sources`, `.table-wrap` (yatay kaydırma), sekmeler sarılır, başlık sıkışır, sağlık çipleri gizlenir, çekmece tam ekran |
| `web/src/hooks.ts` | `useMediaQuery` |
| `web/src/components/FindingsTable.tsx` | ≤640px'de tablo yerine **kart listesi**; "Why?" açıklaması kartın altında tam genişlikte |
| `web/src/pages/ScansPage.tsx` | Telefonda kart listesi (marka, girdi, durum, sayaçlar, Open/Cancel/Delete) |
| `web/src/pages/*.tsx`, `components/*.tsx`, `Layout.tsx` | Sabit inline grid'ler sınıflara taşındı; sayfa başlıkları ve düğmeler sarılır; klavye ipuçları telefonda gizli |

Yalnızca `web/src` değişti.

## Silinen (taşınan) dosyalar
`scripts/watchlist_scan.py`, `watchlist_diff.py`, `scrape_and_triage.py`,
`serper_hunt.py`, `website_hunt.py`, `crtsh_hunt.py` → `scripts/legacy/`

## Çalıştırma
```
pip install -e ".[api,dev,llm,icons,live,serper,whois]"
cp .env.example .env         # SERPER_API_KEY ekle
cd web && npm install && npm run build && cd ..
python -m brandguard.api     # http://127.0.0.1:8000
pytest -q                    # 382 passed
ruff check .
python scripts/evaluate.py   # metrikler değişmedi
```

## Git
```
git checkout -b feat/v2-console
git add -A
git commit -m "feat: v2 product console (API, SQLite, React UI, input resolution, hardening)"
git checkout main; git merge feat/v2-console; git push
```
