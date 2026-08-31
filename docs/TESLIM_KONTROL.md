# Teslim Kontrol Haritası

Brief'in her maddesini "istendi -> nerede karşıladım -> durum" olarak eşler.
Görüşme hazırlığı ve öz-denetim için; repoya girmesi zorunlu değil. Amaç:
her isteği repoda tek bir yere bağlayabilmen, ve neyi bilinçli eksik
bıraktığını dürüstçe bilmen.

Durum işaretleri: [tam] karşılandı, [fazla] istenmeden eklendi, [eksik] bilinçli
sınır, [not] açıklama.

---

## Çekirdek: iki aşamalı sistem

| İstenen | Nerede | Durum |
|---|---|---|
| Kurum profili girdisi | `schema.py` BrandProfile; `data/profiles/*.json` | [tam] |
| Gerekçeli taklit listesi çıktısı | `run.py`, `Verdict.to_analyst_json` | [tam] |
| Aşama 1: keşif / aday havuzu | `discovery/` (adapters, query_expansion) | [tam] |
| Kaynak seçimi + gerekçe | mock 3 kaynak + live Play; K-013, K-028 | [tam] |
| Normalizasyon katmanı | `adapters.py` + `parsing.py`; 3 şema -> AppRecord | [tam] |
| Sorgu stratejisi (en kritik) | `query_expansion.py`; homoglyph/typo/leet/multigraph/tr; kapsama %100 ölçüldü (K-011, K-012) | [tam] |
| Aşama 2: triage / ayıklama | `triage/` (veto, signals, fusion, T1, T2) | [tam] |
| Verilen tüm sinyaller | isim, geliştirici+geçmiş, açıklama, ikon, izin, indirme, tarih | [tam] |
| Kullanıcı yorumları sinyali | tehdit modelinde düşük ağırlık gerekçesiyle atlandı | [eksik] |
| Çelişen sinyalleri tartma (çözümün özü) | veto hiyerarşisi + doyumlu füzyon + K-006 gri bölge | [tam] |

Not [eksik] yorumlar: brief sinyaller arasında saydı ama zorunlu kılmadı.
Saldırgan-kontrollü ve satın alınabilir olduğu için (tehdit modeli) bilinçli
minimal tuttuk. Görüşmede "bilerek atladım, şu sebeple" diye savunulur.

---

## Etiket şeması

| İstenen | Nerede | Durum |
|---|---|---|
| 6 etiketin tamamı | `schema.py` Label enum | [tam] |
| official / impersonation / repackaged | veto + fusion | [tam] |
| third_party_legitimate / unrelated | benign split, K-016 | [tam] |
| uncertain (meşru cevap) | K-018 escalate; zorlama karar yok | [tam] |

---

## Çıktı formatı

| İstenen | Nerede | Durum |
|---|---|---|
| {app_id, source, label, confidence, evidence} | `to_analyst_json` | [tam] |
| evidence denetlenebilir olmalı | her sinyal insan-okur cümle üretir | [tam] |
| "model şüpheli buldu" olmamalı | evidence somut olgular ("16 gün önce", "SMS izni") | [tam] |

---

## Dört kısıt

| İstenen | Nerede | Durum |
|---|---|---|
| 1. Yanlış pozitif < %5 | `metrics.py` takedown_false_positive_rate; ölçüldü **%0** | [tam] |
| 2. Kendi test setini kur | 44 geliştirme + 8 kilitli holdout; `docs/EVALUATION_SET.md`; K-005 | [tam] |
| Test seti dokümante (kaç örnek, nasıl etiketli, hangi zorluk) | EVALUATION_SET.md + K-024/K-025 | [tam] |
| Ekosistem + üçüncü parti zorunlu (ipucu) | L2, L8 katmanları en kalabalık | [tam] |
| 3. Maliyet ve gecikme | kaskad; %84 T0'da biter; tier_usage raporu | [tam] |
| 4. Girdi güvenilmez | tehdit modeli baştan bunun üstüne; injection savunması (K-021); L11 testi | [tam] |

---

## Teslim gereksinimleri

| İstenen | Nerede | Durum |
|---|---|---|
| Çalışır kod + README kurulum | `README.md`, `pip install -e ".[dev,icons]"` | [tam] |
| Değerlendirme sonuçları + nasıl elde edildi | `scripts/evaluate.py`, README, K-024 | [tam] |
| KARARLAR.md: hangi yaklaşım/neden | 31 karar (K-001..K-031) | [tam] |
| KARARLAR.md: denedim-bıraktım | "Tried and Abandoned" tablosu | [tam] |
| KARARLAR.md: bilinen zayıflıklar | "Known Weaknesses" bölümü | [tam] |
| KARARLAR.md: bir ay daha | "With One More Month" bölümü | [tam] |

---

## Değerlendirme kriterleri (neye bakacaklar)

| Kriter | Nasıl karşılandı | Durum |
|---|---|---|
| Problem anlayışı | sinyal füzyonu, çelişki çözümü, kolay/zor ayrımı (11 katman) | [tam] |
| Değerlendirme disiplini | dürüst set, anlamlı metrik, kalibrasyon ölçülüp düzeltildi (K-024) | [tam] |
| Ürün farkındalığı | analist çıktısı, FP maliyeti ciddiye alındı, takedown sıralaması | [tam] |
| Mühendislik | okunur kod, adaptör genişletilebilirliği, kaskad maliyeti, 102 test | [tam] |
| Dürüstlük | sınırlar KARARLAR'da yazılı, hiçbir eksik gizlenmedi | [tam] |

---

## İstenmeden yaptıklarımız (fazladan değer)

| Ne | Nerede | Neden |
|---|---|---|
| Gerçek Google Play kaynağı | `live_google_play.py`; K-028/29/30 | mock->gerçek geçişi kanıtlar |
| Kripto sektörü genelleme demosu | `data/demo/`; K-027 | ezberlenmedi kanıtı |
| Kırmızı takım LLM | `eval/redteam.py`; K-007 | test setini AI ile zorlama |
| İki AI sağlayıcı (Anthropic + OpenAI) | `adjudicator.py`; K-021 | sağlayıcı-bağımsızlık |
| Öğrenme dokümanları (Türkçe) | `docs/learn/` | derin kavrayış (teslimat dışı) |

---

## Bilinçli eksikler (dürüstçe)

| Ne | Neden atlandı | Nerede yazılı |
|---|---|---|
| Yorum sinyali | saldırgan-kontrollü, düşük sinyal/maliyet | tehdit modeli |
| İkon T1 gerçek veride | sentetik ikonla doğrulandı, gerçek app ikonuyla değil | K-019 |
| unrelated/third_party ayrımı | semantik, ucuz sinyalle çözülemez | K-016, bilinen zayıflık |
| Gerçek veride hesap yaşı/doğrulama | scraper vermiyor, sistem orada temkinli | K-028 |

Brief "eksik bırakmak serbest, yeter ki yaz" diyor. Hepsi yazılı. Tek kırmızı
çizgi olan "yapılmamışı yapılmış gösterme"ye hiç düşülmedi.

---

## Demo görüşmesi hazırlığı

| Beklenen | Hazırlık |
|---|---|
| Sistem üzerinden geçiş | KARARLAR.md sırayla anlatır; docs/learn/ satır satır |
| Görülmemiş kayıtları geçirme | `run.py --records <yeni.json>`; kripto demosu prova | 
| Ölçekleme / canlıya alma tartışması | kaskad maliyeti, live source dayanıklılığı, "bir ay daha" listesi |

Görüşmede sık sorulabilecekler ve cevabın yeri:
- "String metriği neden bu?" -> K-009 (ölçtüm, çok boyutlu)
- "LLM'e ne kadar güveniyorsun?" -> K-006/K-021 (sinyal verir, karar vermez)
- "FP'yi nasıl garanti ettin?" -> K-018 (saldırgan-dışı destek şartı), %0 ölçüm
- "Gerçek veride ne olur?" -> K-028/29/30 (test ettim, bug buldum, düzelttim)
- "Zayıflığın ne?" -> unrelated/third_party, dürüstçe, K-016
