# Career Atlas – ilan toplayıcı

Bu depo her gece GitHub Actions ile çalışır:
1. `companies.csv` içindeki şirketlerin kariyer sitelerinden en yeni ilanları çeker (şirket başına 50).
2. İlan açıklamalarından istenen dilleri ve anahtar kelimeleri çıkarır.
3. Sonucu `data/jobs.json` dosyasına yazar. Site ilanları bu dosyadan okur.
4. Her gece, bağlayıcısı olmayan 40 şirketin ilan sistemini (Workday, Greenhouse, SuccessFactors…) otomatik tespit etmeyi dener.

## Kurulum (bir kez)
1. GitHub'da yeni bir depo aç: **New repository** → ad: `career-atlas` → **Public** → Create.
2. Bu zip'in içindekileri depoya yükle: **Add file → Upload files** → klasörleri sürükle bırak → **Commit changes**.
   `.github` klasörü gizli olabilir; görünmüyorsa bilgisayarında gizli dosyaları göster.
3. **Settings → Actions → General → Workflow permissions → Read and write permissions** → Save.
4. **Actions** sekmesi → **Nightly job crawl** → **Run workflow**. İlk çalıştırma birkaç dakika sürer.
5. Bittiğinde `data/jobs.json` güncellenir; `data/status.json` her şirketin sonucunu gösterir (kaç ilan, hata var mı, bağlayıcı yok mu).

## Şirket eklemek
`companies.csv` dosyasına bir satır ekle. `connector` ve `key` biliniyorsa yaz, bilinmiyorsa boş bırak (gece otomatik tespit denenir).

| connector | key örneği |
|---|---|
| workday | `dow|wd1|ExternalCareers` |
| successfactors | `jobs.sabic.com` veya `/go/...` kategori adresi |
| greenhouse / lever / ashby / smartrecruiters | şirketin pano adı |
| oracle_hcm | `eeho.fa.us2.oraclecloud.com|CX_45001` |
| eightfold_pcsx | `apply.careers.microsoft.com|microsoft.com` |
| amazon / google / apple | boş |
| jsonld | site haritası olan alan adı |

## Notlar
- İstekler yavaş ve düşük hacimli yapılır; robots.txt ve sitelerin kullanım şartlarına uyun.
- Cloudflare gibi bot korumalı siteler (ör. SAP) atlanır; doğrulamalar aşılmaz.
- `crawler/ats_tools.py` içindeki `UA` satırına kendi iletişim adresinizi yazın.
