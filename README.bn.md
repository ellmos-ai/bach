<!-- worldset: {"translated_from_sha256": "baef5439fd109dda96de98527f6aa5a716025d9b1f22e231c25c7cc1a5ab1677", "translator": "gpt-6-luna", "translated_at": "2026-10-25T04:35:38.566497+00:00"} -->
<img src="assets/banner_v2.png" width="100%" alt="BACH Banner">

# ellmos BACH — LLM-এর জন্য টেক্সট-ভিত্তিক অপারেটিং সিস্টেম

> যে প্রবাহ সবকিছুকে একত্র করে।

[![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)](https://python.org)
[![লাইসেন্স: MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![সংস্করণ](https://img.shields.io/badge/Version-v3.15.0-orange)](CHANGELOG.md)
[![অবস্থা](https://img.shields.io/badge/Status-Production--Ready-brightgreen)](ROADMAP.md)
[![পরীক্ষা](https://img.shields.io/badge/Tests-4436%20collected-blue)](system/tests/)
[![সর্বশেষ যাচাই](https://img.shields.io/badge/Last_Checked-2026--10--18-brightgreen)](CHANGELOG.md)
[![দায়বদ্ধতা](https://img.shields.io/badge/Haftung-%C2%A7_521_BGB-blue)](https://www.gesetze-im-internet.de/bgb/__521.html)
[![নিরাপত্তা SLA](https://img.shields.io/badge/Security_Response-48h_dual_SLA-blue)](SECURITY.md)

**সংস্করণ:** v3.15.0

## 🎬 ডেমো ভিডিও

BACH-কে কাজ করতে দেখুন — ড্যাশবোর্ড, Codex ব্যাকএন্ড এবং অপারেটর নির্দেশনা, ২:২২ মিনিটে:

[![BACH ডেমো — স্থানীয়-প্রথম LLM অপারেটিং সিস্টেম (2:22)](assets/bach-demo-preview.png)](https://youtu.be/Gv5nxF8HssU)

### স্ক্রিনশট (শীঘ্রই আসছে)
BACH GUI 0.2.29-এর প্রকৃত স্ক্রিনশট শীঘ্রই আসছে। নামকরণ স্কিম এবং ন্যূনতম পরিধি ইমেজ-চুক্তিতে রয়েছে: [assets/gui/README.md](assets/gui/README.md).

## OpenAI Codex ও GPT-5.6 দিয়ে তৈরি

BACH Codex-কে একদিকে প্রধান রানটাইম ব্যাকএন্ড হিসেবে, অন্যদিকে রিপোজিটরি উন্নয়নের অংশীদার হিসেবে ব্যবহার করে। নির্দিষ্ট অটোমেশন সময়সূচি, মডেল রুট এবং নিরীক্ষাযোগ্য সেশন ID-এর জন্য নিচের [যাচাইকৃত Build Week অ্যাট্রিবিউশন](#openai-build-week--codex-and-gpt-56) দেখুন।

## ভাষা

README নথিপত্র এগারোটি ভাষায় উপলভ্য। রানটাইম অনুবাদের পরিধি আলাদাভাবে বিবেচনা করা হয় এবং বর্তমান রিলিজ স্ন্যাপশটে de, en, es, ru, ja ও zh অন্তর্ভুক্ত রয়েছে।

[English](README.md) | [Deutsch](README.de.md) | [Español](README.es.md) | [简体中文](README.zh.md) | [日本語](README.ja.md) | [Русский](README.ru.md) | [Français](README.fr.md) | [हिन्दी](README.hi.md) | [العربية](README.ar.md) | **বাংলা** | [Português](README.pt.md)

বর্তমান রিলিজ কনফিগারেশন স্ন্যাপশট `system/exports/translations/languages_config.release.json`-এ `de`, `en`, `es`, `ru`, `ja` এবং `zh` সক্রিয় করে, এবং সংশ্লিষ্ট লোকেল ফাইল `system/exports/translations/locales/`-এ রপ্তানি করে। ক্রলার ও সরাসরি ভাষা-প্রবেশের জন্য প্রতিটি ভাষার নিজস্ব `README.md` ফাইলও `docs/i18n/<lang>/`-এর অধীনে রয়েছে।

উপরের তালিকা ডকুমেন্টেশনের উপলভ্য অনুবাদ-ভাষা দেখায়। GUI, CLI এবং API-এর রানটাইম ভাষা-সমর্থন রিলিজ কনফিগারেশন দ্বারা নির্ধারিত হয়; শুধু এই README অনুবাদ করলে সেই সমর্থন বাড়ে না।

<p align="center">
  <img src="overview.jpg" alt="BACH Overview" width="700">
</p>

## সারসংক্ষেপ

**BACH** একটি টেক্সট-ভিত্তিক অপারেটিং সিস্টেম, যা বৃহৎ ভাষা মডেলকে (LLM) স্বয়ংক্রিয়ভাবে কাজ করতে, শিখতে এবং নিজেদের সংগঠিত করতে সক্ষম করে। **ellmos** পরিবারের (অতিবৃহৎ ভাষা মডেলের অপারেটিং সিস্টেম) অংশ হিসেবে BACH কাজ ও জ্ঞান ব্যবস্থাপনা, অটোমেশন এবং LLM অর্কেস্ট্রেশনের জন্য পূর্ণাঙ্গ অবকাঠামো দেয়।

## 🧭 মূল গভর্ন্যান্স: পরিচয় ও কর্তৃত্বের প্রবাহ, ৩-কারণ ডকুমেন্টেশন মডেল এবং স্বচ্ছ সিদ্ধান্ত প্রক্রিয়াকরণ নিয়ম

BACH এবং Ocean **স্বচ্ছ, নিরীক্ষণযোগ্য এবং ব্যবহারকারী-কনফিগারযোগ্য সিদ্ধান্ত প্রক্রিয়াকরণ নিয়মের (`decision_processing_rules`)** মাধ্যমে তাদের স্বায়ত্তশাসিত আচরণ পরিচালনা করে। প্রতিটি কর্তৃত্ব পরীক্ষা, ডকুমেন্টেশন পার্থক্যের শ্রেণিবিন্যাস এবং অ্যাকশন শাখা একটি নির্ধারক অডিট রসিদ (`decision_rule_trace`) নির্গত করে।

### 1. পরিচয়, ৩-স্তরের কর্তৃত্ব টানেলিং এবং "কর্তৃত্ব মরুভূমি" থেকে সুরক্ষা

- **পরিচয় বনাম কর্তৃত্ব:** **পরিচয়** ওএস অ্যাকাউন্ট এবং নিবন্ধিত ডিভাইস/চ্যানেলের সাথে নোঙর করা থাকে (গোপন তথ্য স্থানীয় কীরিংয়ে অদৃশ্য থাকে)। **কর্তৃত্ব** ব্যবহারকারীর কাছ থেকে **অপারেটর চ্যানেল** (কনসোল, টেলিগ্রাম, সিস্টেম জিইউআই চ্যাট) হয়ে প্রেরিত সাব-এজেন্ট এবং ব্যাকগ্রাউন্ড কর্মীদের কাছে প্রবাহিত হয়।
- **প্রকৃতি (স্বয়ংক্রিয় ক্ষয় ও পরিবর্তন) বনাম রূপান্তরকরণ/টেরাফর্মিং (উদ্দেশ্যমূলক পরিবর্তন):** ক্ষয় এবং বিচ্যুতি স্বাভাবিকভাবে সিস্টেম ব্যবহারের মাধ্যমে ঘটে (প্রসঙ্গ সংকোচন, সেশন পরিবর্তন, সময়ের প্রবাহ) — কোনো কৃত্রিম মেয়াদোত্তীর্ণ ক্রনজব বৈধ সিদ্ধান্ত বাতিল করে না। `DECISIONS.md`, `AKTUELLER-PLAN.md`, `USER.md` বা কোডের উদ্দেশ্যমূলক সম্পাদনা হলো **টেরাফর্মিং (Terraforming)**: পুরানো এন্ট্রিগুলি মূল উৎসেই সরাসরি `superseded` হিসেবে চিহ্নিত হয়।
- **৩-স্তরের কর্তৃত্ব টানেলিং এবং অভ্যন্তরীণ-প্রথম ক্যাসকেড (Inward-First) (`open-ocean/tools/escalation_ladder.py`):**
  1. **স্তর ১ — শব্দার্থিক কর্তৃত্ব টানেলিং (~৮০% দৈনন্দিন বিপরীতমুখী কাজ):** একটি সক্রিয় লক্ষ্য/পরিকল্পনার (`authority_ref`, `active_goal_or_plan_id`) মধ্যে দ্রুত সম্পাদন, যা ব্যবহারকারীর কাছে অপ্রয়োজনীয় প্রশ্ন এড়ায় (**`error_authority_desert` / কর্তৃত্ব মরুভূমি**)।
  2. **স্তর ২ — নির্ধারক উদ্ধৃতি-প্রমাণ টানেল (~১৫% থ্রেশহোল্ড ট্রানজিশন, `ellmos-authority-evidence`):** NemoFold-এর `evidence.py` থেকে প্রাপ্ত; ১ মিলিসেকেন্ডেরও কম সময়ে (`validate_quote_tunnel_evidence`) যাচাই করে যে প্রদত্ত উদ্ধৃতি (`literal_quote`) মূল উৎসে (`DECISIONS.md`, `transcript.jsonl`, `AKTUELLER-PLAN.md`) **হুবহু শব্দে শব্দে** এবং `superseded` ছাড়া বিদ্যমান কি না।
  3. **স্তর ৩ — কঠোর ক্রিপ্টোগ্রাফিক এবং লক গেট (~৫% অপরিবর্তনীয় বা উচ্চ-ঝুঁকিপূর্ণ কাজ):** `lock_status.py` (`LOCK.user.*`), সল্টযুক্ত নিরাপত্তা প্রশ্ন (`ellmos-installer`), এবং Ed25519 `capability-grant.v1` সনদের মাধ্যমে কার্যকর।

```mermaid
flowchart TD
    classDef userLayer fill:#e0f2fe,stroke:#0284c7,stroke-width:2px,color:#0369a1
    classDef cogLayer fill:#ecfdf5,stroke:#059669,stroke-width:2px,color:#065f46
    classDef tunnelLayer fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#92400e
    classDef errorLayer fill:#fee2e2,stroke:#dc2626,stroke-width:2px,color:#991b1b

    subgraph L0["1. উৎস: প্রকৃতি (বিচ্যুতি) বনাম টেরাফর্মিং (উদ্দেশ্যমূলক)"]
        U["অপারেটর চ্যানেলে ব্যবহারকারী
(কনসোল, টেলিগ্রাম, জিইউআই চ্যাট)"]:::userLayer
        TF["টেরাফর্মিং (উদ্দেশ্যমূলক রূপদান)
DECISIONS.md, পরিকল্পনা, USER.md, policy-registry"]:::userLayer
        NAT["প্রকৃতি ও ভূত্বক (স্বয়ংক্রিয় বিচ্যুতি)
প্রসঙ্গ সংকোচন, সেশন বদল, সময়"]
        U -->|"রূপ দেয়"| TF
    end

    subgraph L1["2. জ্ঞানীয় সিস্টেম ও ৩-স্তরের কর্তৃত্ব টানেলিং"]
        COG["জ্ঞানীয় সিস্টেম + WorkflowHookers
(মেটাকগনিশন, লক্ষ্য, পরিকল্পনা, দক্ষতা -> কাজের ইচ্ছা)"]:::cogLayer
        T1["স্তর ১ (~৮০% বিপরীতমুখী)
শব্দার্থিক কর্তৃত্ব টানেলিং"]:::tunnelLayer
        T2["স্তর ২ (~১৫% থ্রেশহোল্ড)
নির্ধারক উদ্ধৃতি টানেল (<1ms হুবহু যাচাই)"]:::tunnelLayer
        T3["স্তর ৩ (~৫% অপরিবর্তনীয়)
কঠোর গেট (LOCK.user / নিরাপত্তা হ্যাশ / Ed25519)"]:::tunnelLayer
        U --> COG
        TF --> COG
        COG --> T1
        COG --> T2
        COG --> T3
        TF -.->|"হুবহু মিল"| T2
        NAT -.->|"ক্ষয়প্রাপ্ত উদ্ধৃতি ব্যর্থ"| T2
    end

    subgraph L2["3. কর্তৃত্ব পরীক্ষক, অভ্যন্তরীণ-প্রথম ক্যাসকেড ও প্রতিফলন"]
        CHK{"কর্তৃত্ব পরীক্ষক:
কাজ করার অনুমতি আছে?"}:::tunnelLayer
        ACT["হ্যাঁ: অবিলম্বে সম্পাদন করুন"]:::cogLayer
        ASK["না: অভ্যন্তরীণ-প্রথম ক্যাসকেড (Inward-First)
1. লক্ষ্য/প্রসঙ্গ -> 2. DECISIONS/USER.md
-> 3. মূল অর্কেস্ট্রেটর -> 4. ব্যবহারকারী গেট"]:::tunnelLayer
        REF["কাজ-পরবর্তী প্রতিফলন ও শিক্ষা
কর্তৃত্ব মরুভূমি (error_authority_desert) প্রতিরোধ করে"]:::errorLayer

        T1 --> CHK
        T2 --> CHK
        T3 --> CHK
        CHK -->|"হ্যাঁ"| ACT
        CHK -->|"না"| ASK
        ASK -->|"সমাধান হয়েছে"| ACT
        ACT --> REF
    end
```

### 2. ৩-কারণ ডকুমেন্টেশন মডেল এবং কনফিগারযোগ্য সিদ্ধান্ত প্রক্রিয়াকরণ নিয়ম (`system/tools/llmauto/config.json`)

যখন স্বয়ংক্রিয় ডকুমেন্টেশন যাচাইকরণ (`ellmos-doc-keeper` + NemoFold দাবি যাচাইকরণ) ডকুমেন্টেশন (`system/docs/help/*.txt`, `README.md`, `SKILL.md`, GUI `/help`) এবং পরিমাপ করা কোড বাস্তবতার মধ্যে অমিল শনাক্ত করে, তখন এটি **কখনোই কাঙ্ক্ষিত আর্কিটেকচার অন্ধভাবে ওভাররাইট করে না**। পরিবর্তে, `classify_doc_reality_diff()` অমিলকে **৩টি নির্ধারক কারণে** শ্রেণিবদ্ধ করে, এবং `resolve_doc_machine_dispatch()` স্বচ্ছ ও সমন্বয়যোগ্য **সিদ্ধান্ত প্রক্রিয়াকরণ নিয়ম** অনুযায়ী এটি পরিচালনা করে:

| কারণ (`classify_doc_reality_diff`) | অর্থ | স্বচ্ছ কর্ম শাখা (`selected_branches` — একক বা যৌথ) |
|---|---|---|
| **1. `unintended_erosion`** *(অনিচ্ছাকৃত ক্ষয় / বিচ্যুতি)* | ডকুমেন্টেশন প্রত্যাশিত আচরণ বর্ণনা করে, কিন্তু কোড বা পরিষেবা অনিচ্ছাকৃতভাবে ভেঙে গেছে বা বিচ্যুত হয়েছে। | **ডকুমেন্টে SOLL (কাঙ্ক্ষিত লক্ষ্য) বজায় রাখুন** + IST (বর্তমান অবস্থা) সতর্কতা দিন + **`["local_taskplan", "user_notification"]`** প্রেরণ করুন (ব্যাকগ্রাউন্ড কর্মীর জন্য P1 মেরামত টাস্ক তৈরি করে এবং ব্যবহারকারীকে অবহিত করে; ঐচ্ছিকভাবে `local_genie_marblerun` বা `gitlab_wishes_come_true` এর সাথে সমন্বয়যোগ্য)। |
| **2. `planned_terraforming_pending`** *(পরিকল্পিত টেরাফর্মিং বাকি)* | ডকুমেন্টেশন রোডম্যাপ/`DECISIONS.md` থেকে পরিকল্পিত লক্ষ্য আর্কিটেকচার (SOLL) বর্ণনা করে যা এখনও কোডে সম্পন্ন হয়নি। | বিদ্যমান টাস্ক পরীক্ষা/সমন্বয় করুন বা **`["local_taskplan"]`** এর মাধ্যমে P2 বাস্তবায়ন টাস্ক তৈরি করুন + ডকুমেন্টে **SOLL (টাস্ক আইডি সহ)** বনাম **IST** পরিষ্কারভাবে আলাদা রাখুন। |
| **3. `completed_terraforming_doc_lag`** *(টেরাফর্মিং সম্পন্ন, কিন্তু ডকুমেন্টেশন পিছিয়ে)* | কোড ইচ্ছাকৃতভাবে উন্নত করা হয়েছে (commit/PR/`task_status=done` দ্বারা যাচাইকৃত), কিন্তু ডকুমেন্টেশন পিছিয়ে রয়েছে। | **`["local_doc_update"]`** সম্পাদন করুন: `.txt` সিএলআই সাহায্য, `.md` ডকুমেন্ট, সিএলআই/এপিআই রেফারেন্স এবং অনুবাদ (`de/en/es/ja/ru/zh`) স্থানীয়ভাবে স্বয়ংক্রিয়ভাবে আপডেট করে। |

```mermaid
flowchart TD
    classDef probe fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#92400e
    classDef c1 fill:#fee2e2,stroke:#dc2626,stroke-width:2px,color:#991b1b
    classDef c2 fill:#e0f2fe,stroke:#0284c7,stroke-width:2px,color:#0369a1
    classDef c3 fill:#ecfdf5,stroke:#059669,stroke-width:2px,color:#065f46

    subgraph S1["1. দাবি যাচাইকরণ ও ৩-কারণ শ্রেণিবিন্যাস"]
        CLAIM["ডকুমেন্টের দাবি সংগ্রহ (docs/help/*.txt, README, SKILL.md, GUI /help)
এবং কোড/সিএলআই/টেস্ট বাস্তবতা পরীক্ষা"]:::probe
        CLS{"৩-কারণ ক্লাসিফায়ার
(classify_doc_reality_diff)"}:::probe
        U1["কারণ ১: অনিচ্ছাকৃত ক্ষয়
(কোড/পরিষেবা অনিচ্ছাকৃতভাবে ক্ষতিগ্রস্ত বা বিচ্যুত)"]:::c1
        U2["কারণ ২: পরিকল্পিত টেরাফর্মিং বাকি
(ডকুমেন্ট SOLL, কোড এখনও অসম্পূর্ণ)"]:::c2
        U3["কারণ ৩: টেরাফর্মিং সম্পন্ন
(কোড সচেতনভাবে হালনাগাদ, ডকুমেন্ট পিছিয়ে)"]:::c3
        CLAIM --> CLS
        CLS --> U1
        CLS --> U2
        CLS --> U3
    end

    subgraph S2["2. স্বচ্ছ ও সমন্বয়যোগ্য সিদ্ধান্ত প্রক্রিয়াকরণ নিয়ম (config.json)"]
        RULE{"সিদ্ধান্ত নিয়ম ইঞ্জিন
(resolve_doc_machine_dispatch)
কারণ, ট্রিগার বা স্পষ্ট ওভাররাইড দ্বারা"}:::probe
        B1["শাখা A: local_taskplan (ডিফল্ট)
ব্যাকগ্রাউন্ড কর্মীর (Buddha / Cloud) জন্য স্থানীয় টাস্কপ্ল্যানে
P1/P2 মেরামত বা নির্মাণ টাস্ক তৈরি করুন"]:::c3
        B2["শাখা B: local_genie_marblerun
স্থানীয় MarbleRun চেইন চালান
(chains/wishes-come-true-local.json)"]:::c2
        B3["শাখা C: gitlab_wishes_come_true
ডেভেলপার সুবিধা (config.json-এ wishes_redirect)
local-genie / wishes-come-true এর দিকে"]:::probe
        B4["শাখা D: user_notification
জিইউআই ইনবক্স / টেলিগ্রামের মাধ্যমে অপারেটরকে জানান"]:::c1
        B5["শাখা E: local_doc_update
.txt/.md ডকুমেন্ট, সিএলআই/এপিআই রেফারেন্স এবং i18n হালনাগাদ করুন"]:::c3

        U1 --> RULE
        U2 --> RULE
        U3 --> B5
        RULE -->|"সমন্বয়যোগ্য"| B1
        RULE -->|"সমন্বয়যোগ্য"| B2
        RULE -->|"সমন্বয়যোগ্য (ocean-dev)"| B3
        RULE -->|"সমন্বয়যোগ্য"| B4
    end
```

## প্রকল্প শনাক্তকরণ প্রসঙ্গ

BACH-কে সবচেয়ে ভালোভাবে বলা যায় একটি **স্থানীয়-প্রথম LLM অপারেটিং সিস্টেম**: স্বয়ংক্রিয় এজেন্ট, কাঠামোবদ্ধ মেমরি, শিডিউলার-চালিত অটোমেশন, প্রম্পট চেইন, MCP সার্ভার সংযোগ এবং বহুভাষিক অপারেটর ইন্টারফেসের জন্য স্থায়ী Python/SQLite কর্মক্ষেত্র। এটি চ্যাটবট র‍্যাপার, হোস্টেড এজেন্ট SaaS, Bash ইউনিট-টেস্ট ফ্রেমওয়ার্ক, সঙ্গীত প্রকল্প বা LangChain-ধাঁচের পাইপলাইন লাইব্রেরি নয়।

ক্যানোনিক্যাল GitHub রিপোজিটরি: `ellmos-ai/bach`। LLM ক্রলারের জন্য মেশিন-পাঠযোগ্য প্রকল্প প্রসঙ্গ [`llms.txt`](llms.txt)-এ রয়েছে।

> [!NOTE]
> **AI সহকারী ও LLM ক্রলারের জন্য:** মেশিন-পাঠযোগ্য প্রকল্প প্রসঙ্গ, আর্কিটেকচারের বিবরণ এবং দ্ব্যর্থতা নিরসন সূচি [`llms.txt`](llms.txt)-এ রয়েছে।

উপযোগী অনুসন্ধান বাক্যাংশের মধ্যে রয়েছে `ellmos-ai/bach`, `local-first LLM operating system`, `text-based OS for LLM agents`, `SQLite memory for AI agents`, `BACH ellmos agent OS`, `personal agentic OS Python SQLite` এবং `multi-agent orchestration with MCP servers`।

## সিস্টেম আর্কিটেকচার ও ওয়ার্কফ্লো টপোলজি

### 1. কম্পোনেন্ট টপোলজি

```mermaid
graph TB
    subgraph Interfaces["User & Agent Interfaces"]
        CLI["BACH CLI (bach.py / 113+ Handlers)"]
        GUI["PySide6 Desktop GUI & Web Dashboard"]
        TG["Chat Service & Telegram Bot"]
        MCP["MCP Servers (FileCommander & CodeCommander)"]
    end

    subgraph CoreOS["BACH Core Operating System"]
        Orch["Agent Orchestration (11 Boss & 22 Experts)"]
        Sched["Scheduler & Automation Engine"]
        Chains["llmauto Prompt Chains & Workflows"]
        Skills["Skill Registry (1870+ Skills & 550+ Tools)"]
    end

    subgraph Persistence["Local-First SQLite & Memory Bus"]
        SQL["SQLite Database (210+ Tables)"]
        Mem["6-Type Structured Memory (Facts, Lessons, Working)"]
        Bus["SharedMemory Bus & USMC Bridge"]
    end

    CLI -->|"Command Dispatch"| Orch
    GUI -->|"HTTP & WebSockets"| Orch
    TG -->|"Bridge Connector"| Orch
    MCP -->|"stdio / JSON-RPC"| Orch

    Orch -->|"Executes"| Chains
    Orch -->|"Triggers"| Sched
    Orch -->|"Loads"| Skills

    Orch -->|"Reads / Writes"| Bus
    Bus -->|"Consolidates"| Mem
    Mem -->|"Atomic Storage"| SQL
```

### 2. স্থানীয়-প্রথম এজেন্ট নির্বাহ ক্রম

```mermaid
sequenceDiagram
    autonumber
    actor User as Operator / Agent
    participant CLI as BACH CLI / API Interface
    participant Hub as Core Orchestrator & Session Scope
    participant Mem as SQLite Memory & SharedMemory Bus
    participant LLM as Pluggable Backend (Local Ollama / CLI)
    participant Tool as Tool & Skill Execution Engine

    User->>CLI: Issue task or workflow command
    CLI->>Hub: Dispatch request with session token
    Hub->>Mem: Query context, lessons, and working memory
    Mem-->>Hub: Return relevant facts and active constraints
    Hub->>LLM: Formulate prompt with local context (zero egress)
    LLM-->>Hub: Stream plan and requested tool invocations
    Hub->>Tool: Execute vetted tool / handler locally
    Tool-->>Hub: Return tool execution output
    Hub->>Mem: Record new facts, lesson feedback, and audit log
    Hub-->>CLI: Format structured response (JSON / text)
    CLI-->>User: Present completed result to operator
```

<a id="openai-build-week--codex-and-gpt-56"></a>
## OpenAI উন্নয়ন সপ্তাহ — Codex ও GPT-5.6

BACH Codex-কে দুটি আলাদা ভূমিকায় ব্যবহার করে:

- **রানটাইম ব্যাকএন্ড:** `codex-cli` পাঁচটি পরিবর্তনযোগ্য চ্যাট ব্যাকএন্ডের একটি; BACH এজেন্ট `codex exec`-এর মাধ্যমে কোডিং কাজ অর্পণ করতে পারে।
- **রিপোজিটরি উন্নয়ন:** তিনটি সক্রিয় Codex অটোমেশন প্রকল্প রক্ষণাবেক্ষণ করে: `bach-daily-care-and-dev-check`, `bach-start-and-health-checks` এবং `bach-github-release-service`। ২১ জুলাই ২০২৬ থেকে তিনটিই GPT-5.6 (`gpt-5.6-terra`)-এর জন্য কনফিগার করা; প্রথম দুটি প্রতিদিন চলে, আর রিলিজ সার্ভিস সাপ্তাহিক চলে।
- **যাচাইকৃত মডেল রাউটিং:** Codex সেশন `019f85c6-4339-7f13-b8e5-bf1823fd8432`-এ উচ্চ যুক্তি-স্তরের GPT-5.6 Sol সব ৭৮টি অটোমেশন সংজ্ঞা নিরীক্ষা করে BACH উন্নয়ন ও রিলিজ কাজ Terra/high-এ এবং স্বাস্থ্য পরীক্ষা Terra/medium-এ রাউট করেছে।
- **চূড়ান্ত জমা নিরীক্ষা:** Codex সেশন `019f8674-fe9a-7d91-a80f-7ee799e8ced0`-এ GPT-5.6 Sol অপেক্ষমাণ BACH পরিবর্তন পর্যালোচনা ও প্রত্যয়ন করেছে, প্রতিযোগিতা-সংক্রান্ত অ্যাট্রিবিউশন ঠিক করেছে এবং ওয়েব-স্ক্র্যাপিং সুরক্ষা ও রিগ্রেশন পরীক্ষা সম্পন্ন করেছে।

নিরীক্ষাযোগ্যতার জন্য GPT-5.6 অটোমেশন অ্যাট্রিবিউশন ওই কনফিগারেশন পরিবর্তনের পর থেকে প্রযোজ্য; তার আগের অটোমেশন রান আগের Codex মডেল ব্যবহার করেছে।

### প্রধান বৈশিষ্ট্য

- **113+ হ্যান্ডলার** — CLI ও API-তে সিস্টেমের সব ফাংশনের পূর্ণ কভারেজ
- **550+ টুল** — ফাইল প্রক্রিয়াকরণ, বিশ্লেষণ ও অটোমেশনের বিস্তৃত টুল-লাইব্রেরি
- **1870+ স্কিল** — পুনর্ব্যবহারযোগ্য ওয়ার্কফ্লো ও টেমপ্লেট
- **স্কিল সোর্স রেজিস্ট্রি** — `bach skills version bach`, `system/data/skill_sources.json`-এর মাধ্যমে রিপোজিটরি-রুটের ক্যানোনিক্যাল স্কিল খুঁজে পায় এবং অস্পষ্ট ফাইলনামজনিত বিচ্যুতি ছাড়াই ঐচ্ছিক Codex/Claude ব্যবহারকারী কপির সঙ্গে তুলনা করতে পারে
- **71 ওয়ার্কফ্লো টেমপ্লেট** — আগে থেকে তৈরি প্রক্রিয়া
- **4400+ পরীক্ষা** — হ্যান্ডলার, সার্ভিস, GUI ও MCP সার্ভারের বিস্তৃত স্বয়ংক্রিয় কভারেজ
- **জ্ঞানভান্ডার** — শিক্ষা, তথ্য এবং বহুস্তরীয় মেমরি সিস্টেম (৬ ধরনের মেমরি); নতুন রেকর্ডে প্রতিটি এন্ট্রির সঙ্গে BACH সেশনের উৎসতথ্য যোগ হয়, পুরোনো রেকর্ডের লেখক স্পষ্টভাবে অজানা থাকে
- **এজেন্ট CLI** — `bach agent start/stop/list` দিয়ে সরাসরি এজেন্ট নিয়ন্ত্রণ
- **এজেন্ট ডায়াগনস্টিক** — `bach agent doctor [name] [--json]` চালুর আগে Claude CLI-এর প্রাপ্যতা, রানটাইম ডিরেক্টরি, স্কিল ফাইল এবং পুরোনো PID অবস্থা যাচাই করে
- **এজেন্ট অপারেটর নিয়ন্ত্রণ** — `bach agent pause/resume/checkpoint/steer/clear-steer [name] [--json]` অপারেটরকে রান শুরুর আগে বা চলাকালে সহযোগিতামূলক বিরতির অনুরোধ ও নির্দেশনা সাজাতে, নিরাপদ চেকপয়েন্টের স্পষ্ট স্বীকৃতি লিখে রাখতে, সেই অবস্থা `OPERATOR_NOTES.md`-এ প্রতিফলিত করতে, পরবর্তী `bach agent start` স্টার্ট পর্যন্ত অপেক্ষমাণ সংকেত ধরে রাখতে, সেগুলো তৈরি হওয়া সেশনের `CLAUDE.md`-এ প্রবেশ করাতে এবং অটোমেশন-নিরাপদ পোলিংয়ের জন্য নেস্টেড `operator_control` স্ন্যাপশট ও `queued_for_next_start` প্রকাশ করতে দেয়
- **এজেন্ট রানটাইম নীতির ডিফল্ট** — `bach agent start` এখন `--permission-mode`, `--allowed-tools` এবং `--max-turns` গ্রহণ করে; প্রতি-এজেন্ট সুরক্ষার জন্য এজেন্ট SKILL ফ্রন্টম্যাটার থেকেও একই ডিফল্ট আগাম লোড করতে পারে
- **শিডিউলার ডায়াগনস্টিক** — `bach scheduler doctor [--json]` এবং `bach scheduler session doctor [--json]` ব্যাকগ্রাউন্ড সার্ভিস শুরুর আগে অটোমেশন স্ক্রিপ্ট, PID অবস্থা, DB/config/profile সারফেস যাচাই করে এবং পুনরুদ্ধারের পরামর্শ দেয়
- **সেশন নির্দেশনা নিয়ন্ত্রণ** — `bach scheduler session pause/resume/steer/clear-steer [--json]` ডেমন কনফিগারেশন হাতে না বদলে পরবর্তী প্রোফাইল-নির্দিষ্ট স্বয়ংক্রিয় সেশন স্থগিত বা পুনর্নির্দেশ করতে দেয়
- **শিডিউলার রান নিয়ন্ত্রণ** — `bach scheduler pause/resume/steer/clear-steer [--json]` নির্ধারিত শিডিউলার কাজের জন্য একই অপারেটর নিয়ন্ত্রণ দেয়, যার মধ্যে বৈশ্বিক বিরতি ও অপেক্ষমাণ রান নির্দেশনা রয়েছে; কন্ট্রোল ফাইল হাতে বদলাতে হয় না। অপেক্ষমাণ শিডিউলার সংকেত পরবর্তী নিরাপদ চেকপয়েন্ট প্রম্পট পথে llmauto চেইনও প্রস্তুত করে
- **মেশিন-পাঠযোগ্য নিয়ন্ত্রণ ও অবস্থা সারফেস** — `bach agent list/start/stop/pause/resume/checkpoint/steer/clear-steer/status --json`, `bach scheduler status/jobs/session status --json` এবং `bach scheduler session pause/resume/steer/clear-steer --json`-এ কিউ অবস্থা, `queued_for_next_start`, সময়চিহ্ন, চেকপয়েন্ট স্বীকৃতি এবং অপারেটর-নোট মেটাডেটা থাকে, যা অটোমেশনের নিরাপদ পোলিংয়ে সহায়তা করে
- **ওয়ার্কার কিউ ডায়াগনস্টিক** — [নির্বাচন পর্যবেক্ষণ](docs/worker-queue.md) বিদ্যমান worker API-র মাধ্যমে তারিখসহ প্রার্থী সংখ্যা এবং binding, category, priority, tag, ownership ও native claim-সংক্রান্ত প্রত্যাখ্যান দেখায়; নিষ্ক্রিয় পোলিং মডেল ব্লক হিসেবে গণ্য হয় না। প্রমাণীকৃত কনফিগারেশন উত্তরে পৃথক পঠন-মাত্র নির্বাচননীতি থাকে এবং বিদ্যমান GUI কার্ড অপেক্ষার পাঠযোগ্য সারাংশ দেখায়। এসব পর্যবেক্ষণ কাজ বা ফল গ্রহণের অধিকার দেয় না।
- **আপগ্রেড বিচ্যুতি ও মেরামত** — `bach upgrade list <path> --json`, `bach upgrade status/check --json` এবং `bach upgrade repair [--dry-run] [--version <tag>]` ভাঙা বিতরণ মেটাডেটার জন্য অটোমেশন-নিরাপদ সংস্করণ, অবস্থা, বিচ্যুতি, মেরামতের ইঙ্গিত ও পুনরুদ্ধার দেয়
- **পাথ সারফেস** — `bach path` ক্যানোনিক্যাল সিস্টেম/ওয়ার্কস্পেস/DB পাথ, যাচাই, সমাধান সহায়ক ও DB ওভাররাইড টেক্সট বা JSON-এ দেখায়
- **প্রম্পট সিস্টেম** — বোর্ড ব্যবস্থা ও সংস্করণ নিয়ন্ত্রণসহ কেন্দ্রীয় প্রম্পট ব্যবস্থাপনা
- **ইনস্টল নিরাপত্তা গেট** — `skills install`/`plugins load` চলাকালে প্রি-লোড স্থির স্ক্যান স্পষ্ট কোড-ইনজেকশন প্যাটার্ন আটকায়; MCP সেটআপ অনুমোদিত তালিকার প্যাকেজ/কনফিগারেশন fail-closed যাচাই করে; প্লাগইন সেটআপ চুক্তিতে এখন স্পষ্ট shell/desktop/MCP পরীক্ষা লাগে; অবরুদ্ধ স্থানীয় ইমপোর্ট কোয়ারেন্টিনে রাখা হয়
- **মেনিফেস্ট-ফার্স্ট প্লাগইন** — `bach plugins inspect` প্লাগইনের রানটাইম কোড ইমপোর্ট না করে সক্রিয়করণ, সরবরাহকারী/মডেল, সেটআপ ও ক্ষমতার মেটাডেটা আগাম দেখায়
- **কাঠামোবদ্ধ `bach_api` কোর** — `task` এবং `memory` এখন `dir(...)`-এর মাধ্যমে খুঁজে পাওয়া যায় এমন পদ্ধতি দেয়, সাধারণ পড়া/লেখায় Python অবজেক্ট ফেরত দেয় এবং পুরোনো হ্যান্ডলার-ধাঁচের কলের জন্য `raw(...)` রাখে
- **SharedMemory বাস** — দ্বন্দ্ব শনাক্তকরণ ও ক্ষয়সহ বহুএজেন্ট সমন্বয়
- **USMC ব্রিজ** — এজেন্টদের পারস্পরিক যোগাযোগের জন্য United Shared Memory Communication
- **llmauto চেইন** — Claude প্রম্পটকে চেইন ধাপ হিসেবে ব্যবহার করে এবং `bach://` URL সমাধান করে
- **চ্যাট সার্ভিস** — বহু-ব‌্যাকএন্ড Telegram বট (৫টি ব্যাকএন্ড), Control API, Web ড্যাশবোর্ড, বহু-প্ল্যাটফর্ম সিস্টেম ট্রে

## ইনস্টলেশন

```bash
# Clone the repository
git clone https://github.com/ellmos-ai/bach.git
cd bach

# Install dependencies and make `bach` CLI available
pip install -e .

# Pre-flight check
bach setup preflight

# Full install (MCP servers, hooks, secrets, user profile)
bach setup full-install
```

### ঐচ্ছিক অপারেটর কনসোল

বিদ্যমান `ellmos-unified-gui` অপারেটর কনসোল দ্বিতীয় প্রসেস বা দ্বিতীয় Unified GUI কনফিগারেশন ছাড়াই BACH ড্যাশবোর্ডে মাউন্ট করা যায়:

```bash
pip install -e ".[console]"
BACH_GUI_CONSOLE_ENABLED=1 python system/gui/server.py
```

মাউন্ট ডিফল্টভাবে বন্ধ থাকে এবং `/control` ব্যবহার করে। অন্য কোনো নিরঙ্কুশ URL পাথ বেছে নিতে `BACH_GUI_CONSOLE_PREFIX` সেট করুন। ঐচ্ছিক প্যাকেজ না থাকলে বা মাউন্ট করা না গেলে BACH ড্যাশবোর্ড কনসোল ছাড়াই চলতে থাকে। BACH আলাদা লগইন চালু করে না; BACH হোস্টের জন্য Unified GUI-র বিদ্যমান সক্ষমতা-ভিত্তিক আচরণ বজায় থাকে। BACH ড্যাশবোর্ড বর্তমানে `AUTH_ROLE` হোস্ট সেশন দেয় না, তাই এই মাউন্ট ডিফল্ট loopback ঠিকানায় বা বিদ্যমান বিশ্বস্ত প্রবেশসীমার পেছনে রাখুন।

## MCP সার্ভার (Claude Code সংযোগ)

BACH-এ Claude Code, Cursor এবং অন্যান্য IDE-র সংযোগের জন্য অন্তর্নির্মিত Python MCP সার্ভার ও দুটি সহায়ক সার্ভার রয়েছে:

```bash
# Start the built-in BACH server (stdio)
bach mcp serve

# Install and configure MCP servers (recommended)
python system/bach.py setup mcp

# Or manually via npm:
npm install -g ellmos-codecommander-mcp ellmos-filecommander-mcp
```

- **BACH MCP সার্ভার** — হ্যান্ডলার API দিয়ে BACH-এর রিসোর্স, টুল ও প্রম্পট (`bach mcp serve`)
- **[ellmos-codecommander-mcp](https://www.npmjs.com/package/ellmos-codecommander-mcp)** v1.3.14 — কোড বিশ্লেষণ ও রিফ্যাক্টরিং টুল (২১টি টুল)
- **[ellmos-filecommander-mcp](https://www.npmjs.com/package/ellmos-filecommander-mcp)** v1.9.1 — ফাইল ব্যবস্থাপনা ও ব্যাচ অপারেশন (৪৬টি টুল)

## দ্রুত শুরু

```bash
# Fast, side-effect-free metadata
python bach.py --version
python bach.py --help

# Start BACH
python bach.py --startup

# Create a task
python bach.py task add "Analyze project structure"

# Manage agents
python bach.py agent list
python bach.py agent start bueroassistent

# Manage prompts
python bach.py prompt list
python bach.py prompt add "My Prompt" --content "..."

# Check scheduler status
python bach.py scheduler status

# Import versioned everyday-data exports (idempotent)
python bach.py abo import PATH/abotracker-export-v1.json
python bach.py versicherung import PATH/bach-fin-insurances-v1.json

# Register recurring imports only after a valid export file exists
python bach.py abo schedule-import PATH/abotracker-export-v1.json --interval 24h
python bach.py versicherung schedule-import PATH/bach-fin-insurances-v1.json --interval 24h

# Preview and refresh the current monthly/year-to-date finance summary
python bach.py haushalt financial-summary refresh --dry-run
python bach.py haushalt financial-summary refresh

# Shut down BACH
python bach.py --shutdown
```

### Python প্রোগ্রামিং দ্রুতসূচনা

```python
from bach_api import get_api

# Initialize the lightweight, side-effect-free BACH API client
api = get_api()

# Create a tracked task
task = api.task.add("Explore local agent environment")
print(f"Task created: {task.id} - {task.title}")

# Query system status
status = api.system.status()
print(f"BACH status: {status.state} (Active handlers: {status.handlers_count})")
```

`--version`, `--help`, কমান্ড-নির্দিষ্ট সহায়তা এবং বৈশ্বিক `--dry-run` স্টার্টআপ পাথ AutoLogger, ProSync ও কার্যকলাপ ট্র্যাকিং এড়িয়ে চলে। সাধারণ কমান্ড ProSync pull শুরু করার আগে তা জানায় এবং ১৫ সেকেন্ডের স্টার্টআপ বাজেট প্রয়োগ করে। ধীর ট্রানজিটের জন্য স্পষ্ট স্থানীয় বাজেট দরকার হলে `BACH_PROSYNC_STARTUP_TIMEOUT_SECONDS`-কে ১ থেকে ৩০০-এর মধ্যে সেট করুন। Pull ব্যর্থ হলে বা সময়সীমা ছাড়ালে BACH চলতে থাকে, তবে ওই প্রসেসের জন্য প্রস্থানের সময় push নিবন্ধন করে না।

ইমপোর্ট কমান্ডের জন্য নির্দিষ্ট স্কিমা `abotracker-export-v1` এবং `bach.fin_insurances.v1` আবশ্যক। AboTracker বিলিং চক্র নিশ্চিত পরবর্তী-পেমেন্ট তারিখ হিসেবে গণ্য হয় না। নির্ধারিত কাজ সক্রিয়, idempotent ফাইল ইমপোর্ট এবং কেবল বর্তমান উৎস ফাইল যাচাই পাস করার পর তৈরি হয়।

আর্থিক সারাংশে ইমেল থেকে পর্যবেক্ষিত ব্যয়কে বর্তমান পুনরাবৃত্ত সাবস্ক্রিপশন ব্যয়ের হার থেকে আলাদা রাখা হয়। পুরোনো ডুপ্লিকেট সাবস্ক্রিপশন গণনা ও ড্যাশবোর্ড পড়ার জন্য সরবরাহকারী অনুযায়ী বাদ দেওয়া হয়; পরস্পরবিরোধী ডুপ্লিকেট অনুমান বা মুছে না দিয়ে fail-closedভাবে প্রত্যাখ্যাত হয়।

## মূল উপাদান

স্থানীয় ইনফারেন্স বর্তমান মডেল-কল সীমায় স্পষ্ট হোস্ট রিজার্ভ নীতি প্রয়োগ করতে পারে। এটি নেটিভ মডেল পরিচয়, কনফিগার করা প্রসঙ্গ ও মেমরি হেডরুম এবং কাজ, স্লট ও রানটাইম সংরক্ষণের খালি স্থান যাচাই করে। অপেক্ষার অবস্থা ইনফারেন্সের মালিক ফেরত দেয় এবং টুল পুনরায় চালানো ছাড়াই বর্তমান সেশন ধরে রাখে। এই রিজার্ভ বাধা ঐচ্ছিক; এটি মডেল-স্লট নিয়ন্ত্রকের বিকল্প নয় এবং মডেল সক্ষমতার নিশ্চয়তা দেয় না। কনফিগারেশন, যাচাই এবং আলাদা ইনস্টলেশন/রানটাইম গেটের জন্য [স্থানীয় মডেল রিজার্ভ](docs/architecture/LOCAL-MODEL-RESERVE.md) দেখুন।
[মডেল সকেট চুক্তি](docs/architecture/MODEL-SOCKETS.md) নেটিভ সংলাপ ও কানেক্টর কলকে স্থিতিশীল এজেন্ট পরিচয়ের সঙ্গে যুক্ত করে, স্পষ্ট মাইগ্রেশনের সময় কনফিগার করা কানেক্টর লক্ষ্য প্রজেক্ট করে এবং বিদ্যমান সংলাপ প্রসঙ্গ ধরে রাখে। সোর্স যাচাই নেটিভ মাইগ্রেশন বা মডেল সক্ষমতার প্রমাণ নয়।


### 1. কাজ ব্যবস্থাপনা
অগ্রাধিকার, শেষ সময়, ট্যাগ ও প্রসঙ্গ ট্র্যাকিংসহ পূর্ণ GTD সিস্টেম।

### 2. জ্ঞান ব্যবস্থা
তথ্য, শিক্ষা ও স্বয়ংক্রিয় সমন্বয়সহ কাঠামোবদ্ধ মেমরি সিস্টেম (৬ ধরনের মেমরি, 210+ DB টেবিল)।

### 3. এজেন্ট ফ্রেমওয়ার্ক — Ocean ভূমিকা, দ্বৈত রাউটিং এবং নমনীয় প্রোভাইডার সকেট (`ellmos.role-socket-catalog.v1`)
যৌথ Ocean/BACH আর্কিটেকচারে, পরীক্ষিত BACH **বস এজেন্ট (সমন্বয়কারী)** এবং **ডোমেন বিশেষজ্ঞরা** সম্পূর্ণ সংরক্ষিত থেকে **নমনীয় প্রোভাইডার সকেট (`clutch` + `agents-heart` এর মাধ্যমে `model_sockets`)** এর সাথে যুক্ত **প্রোভাইডার-স্বাধীন Ocean ভূমিকা (`roles[]`)** হিসেবে কাজ করে:

- **দ্বৈত রাউটিং (শব্দার্থিক + নির্ধারক):**
  - **শব্দার্থিক রাউটিং:** আমব্রেলা দক্ষতা (`projekt-pipeline-umbrella`, `therapie-umbrella`, `selbstmanagement` ইত্যাদি) এবং `semantic-persona-routing` (`persona_router.py`) গতিশীলভাবে কাজ রাউট করে এবং উপযুক্ত দক্ষতা বান্ডিল ও ব্যক্তিত্ব প্রসঙ্গ সক্রিয় করে।
  - **নির্ধারক রাউটিং:** `ellmos-controlcenter-mcp` (`controlcenter_resolve_semantic_route`, `controlcenter_switch_profile`, `controlcenter_find_skill`) বিভ্রমমুক্ত এবং কঠোর নিয়ম-ভিত্তিক রাউটিং ও প্রোফাইল পরিবর্তন প্রদান করে।
- **নমনীয় প্রোভাইডার সকেট (`reasoning_coordinator`, `domain_specialist`, `fast_worker`):** ভূমিকাগুলি কখনোই কোনো একক বিক্রেতার সাথে কঠোরভাবে আবদ্ধ নয়। প্রতিটি ভূমিকা একটি প্রমিত সকেটে প্লাগ হয় যা রানটাইমে **Claude (`claude`)**, **OpenAI/Codex (`codex`)**, **Gemini/Antigravity (`agy`)**, **Kimi (`kimi`)**, **স্থানীয় Ollama (`ollama`)**, বা **OpenRouter (`openrouter`)** এ সমাধান হয়।
- **৩-ট্যাব এজেন্ট লাইব্রেরি (`/agenten/bibliothek`, `ellmos.agent-library.v1`):** `discover_ocean_agent_library_templates()` স্বয়ংক্রিয়ভাবে BACH সমন্বয়কারী/বিশেষজ্ঞ ক্যাটালগ (`ati`, `bueroassistent`, `finanz-assistent`, `gesundheitsassistent`, `persoenlicher-assistent`, `produktivitaet` + ২২ জন বিশেষজ্ঞ) এবং ৯টি Ocean মডিউল রিপোজিটরিতে (`task-master`, `ticket-master`, `MarbleRun`, `system-auditor`, `compare-race`, `ellmos-installer`, `foerderplaner`, `ai-media-editor`, `clip-storyboard-director`) ঘোষিত **১৭টি সুস্পষ্ট মডিউল ভূমিকা (`roles[]`)** থেকে জিইউআই ও সিএলআই এজেন্ট লাইব্রেরি পূর্ণ করে।
- **অপারেটর নিয়ন্ত্রণ:** `bach agent start/stop/list/pause/resume/checkpoint/steer` চলমান কাজ পরিচালনা, লঞ্চ-পূর্ব নির্দেশনা (`OPERATOR_NOTES.md`), এবং নিরাপদ চেকপয়েন্ট স্বীকৃতি নিয়ন্ত্রণ করে।

<p align="center">
  <img src="sketch_bach_boss_agents.jpg" alt="BACH Boss Agents" width="600"><br>
  <i>চিত্রে BACH-এর মূল সমন্বয়কারী ভূমিকাগুলি (ati, bueroassistent, finanz-assistent, gesundheitsassistent, persoenlicher-assistent) দেখানো হয়েছে, যা এখন ১৭টি মডিউল-ম্যানিফেস্ট ভূমিকার সাথে Ocean-এর নমনীয় প্রোভাইডার সকেটে কাজ করছে।</i>
</p>

```mermaid
flowchart TD
    classDef routeLayer fill:#e0f2fe,stroke:#0284c7,stroke-width:2px,color:#0369a1
    classDef roleLayer fill:#ecfdf5,stroke:#059669,stroke-width:2px,color:#065f46
    classDef socketLayer fill:#fef3c7,stroke:#d97706,stroke-width:2px,color:#92400e

    subgraph R1["1. দ্বৈত রাউটিং স্তর (শব্দার্থিক বনাম নির্ধারক)"]
        SEM["শব্দার্থিক রাউটিং
আমব্রেলা দক্ষতা (*-umbrella) + semantic-persona-routing"]:::routeLayer
        DET["নির্ধারক রাউটিং
ellmos-controlcenter-mcp (resolve_semantic_route / switch_profile)"]:::routeLayer
    end

    subgraph R2["2. Ocean ভূমিকা ও ৩-ট্যাব এজেন্ট লাইব্রেরি (ellmos.agent-library.v1)"]
        COORD["6 সমন্বয়কারী ভূমিকা (পূর্বে BACH বস)
ati, bueroassistent, finanz-assistent, gesundheitsassistent, persoenlicher-assistent, produktivitaet"]:::roleLayer
        EXP["২২+ ডোমেন বিশেষজ্ঞ এবং ১৭টি মডিউল ভূমিকা (roles[])
tasksolver, ticket-master, ticket-writer, marble-controller, doc-keeper, race-starter, foerderplaner-expert, media-creator, storyboard-director"]:::roleLayer
        SEM --> COORD
        DET --> COORD
        COORD --> EXP
    end

    subgraph R3["3. নমনীয় প্রোভাইডার সকেট (model_sockets + clutch + agents-heart)"]
        SOCK["প্রমিত মডেল সকেট
reasoning_coordinator | domain_specialist | fast_worker"]:::socketLayer
        PROV["প্লাগযোগ্য LLM প্রোভাইডার
Claude | Codex/GPT | Gemini/AGY | Kimi | স্থানীয় Ollama | OpenRouter"]:::socketLayer
        COORD --> SOCK
        EXP --> SOCK
        SOCK --> PROV
    end
```

### 4. প্রম্পট সিস্টেম
বোর্ড সংগ্রহ ও পূর্ণ সংস্করণ নিয়ন্ত্রণসহ প্রম্পট টেমপ্লেটের কেন্দ্রীয় ব্যবস্থাপনা (`bach prompt`)।

### 5. চ্যাট সার্ভিস ও ব্রিজ ব্যবস্থা
পরিবর্তনযোগ্য LLM ব্যাকএন্ড (Ollama, Claude CLI, Codex CLI, Claude API, OpenAI API) সহ বহু-ব‌্যাকএন্ড Telegram বট, Web ড্যাশবোর্ডসহ HTTP Control API এবং বহু-প্ল্যাটফর্ম সিস্টেম ট্রে। কানেক্টর ফ্রেমওয়ার্ক ইমেল, WhatsApp ইত্যাদি অতিরিক্ত সার্ভিস এবং USMC Bridge এজেন্টদের পারস্পরিক যোগাযোগ সমর্থন করে।

### 6. অটোমেশন
সময়ভিত্তিক কাজের (চেইন, টাস্ক, স্ক্রিপ্ট) জন্য SchedulerService এবং hook ফ্রেমওয়ার্কে ইভেন্ট-চালিত ওয়ার্কফ্লো।

### 7. SharedMemory
প্রসঙ্গ তৈরি, দ্বন্দ্ব শনাক্তকরণ, ক্ষয় ও পার্থক্য-জিজ্ঞাসাসহ বহুএজেন্ট সমন্বয়।

### 8. llmauto সংযোগ
LLM প্রম্পট হিসেবে চেইন ধাপ, গতিশীল প্রসঙ্গ যোগের জন্য `bach://` URL সমাধানসহ।

## ellmos পরিবার

সব ellmos প্রকল্প ঝরনা থেকে পূর্ণ প্রবাহ পর্যন্ত পানির রূপক অনুসরণ করে:

| স্তর | প্রকল্প | বিবরণ | রিপোজিটরি |
|------|---------|-------------|-------------|
| 1 | **USMC** | United Shared Memory Client — ঝরনা (শুধু শেয়ার্ড মেমরি) | [github.com/ellmos-ai/usmc](https://github.com/ellmos-ai/usmc) |
| 2 | **Rinnsal** | ক্ষুদ্র প্রবাহ — USMC + llmauto (LLM অর্কেস্ট্রেশন), অত্যন্ত কমপ্যাক্ট | [github.com/ellmos-ai/rinnsal](https://github.com/ellmos-ai/rinnsal) |
| 3 | **BACH** | সবকিছু-সংযুক্ত প্রবাহ — 113+ হ্যান্ডলার, 1870+ স্কিল, এজেন্ট, GUI, ব্রিজ | [github.com/ellmos-ai/bach](https://github.com/ellmos-ai/bach) |

## ডকুমেন্টেশন

নেটিভ ডকুমেন্টেশন রক্ষণাবেক্ষণ, সক্রিয়করণ এবং প্রমাণের সীমা:
[DOCS-MAINTENANCE.md](docs/architecture/DOCS-MAINTENANCE.md)।

- **[শেয়ার্ড GUI ও এজেন্ট নিয়ন্ত্রণ](system/docs/help/gui-integration.txt)** — কনজিউমার রিলিজ পিন ও অ্যাডাপ্টার পরীক্ষা
- **[শেখার উৎস ও পর্যালোচনার প্রার্থী](docs/architecture/LEARNING-SOURCE-CONTRACT.md)** — সীমিত উৎস প্রিভিউ ও নিষ্ক্রিয় খসড়া; [কমান্ড সহায়তা](system/docs/help/learning_en.txt)। প্রকাশনা ও স্বাধীন পুনর্ব্যবহারের জন্য আলাদা গ্রহণযোগ্যতা দরকার।
- **[Ocean-BACH স্থানান্তর পরিকল্পনা](OCEAN-TRANSFER-PLAN.md)** — ইনস্টলার সীমা ও ধাপে ধাপে মডিউল স্থানান্তর
- **[অবচয় রেজিস্টার](DEPRICATED.md)** — প্রতিস্থাপন, গ্রহণ ও রোলব্যাক

[English](README.md) | [Deutsch](README.de.md) | [Español](README.es.md) | [简体中文](README.zh.md) | [日本語](README.ja.md) | [Русский](README.ru.md) | [Français](README.fr.md) | [हिन्दी](README.hi.md) | [العربية](README.ar.md) | **বাংলা** | [Português](README.pt.md)
- **[দ্রুতসূচনা নির্দেশিকা](QUICKSTART.md)** — ৫ মিনিটে প্রথম ওয়ার্কফ্লো চালু করুন
- **[ব্যবহারকারী ম্যানুয়াল](BACH_USER_MANUAL.md)** — সম্পূর্ণ নির্দেশিকা
- **[স্কিল ক্যাটালগ](SKILLS.template.md)** — উপলভ্য স্কিলের টেমপ্লেট ও সর্বসাধারণের প্রবেশপথ
- **[এজেন্ট ক্যাটালগ](AGENTS.template.md)** — এজেন্ট ও বিশেষজ্ঞের টেমপ্লেট এবং সর্বসাধারণের প্রবেশপথ
- **[ওয়ার্কফ্লো](WORKFLOWS.template.md)** — এই রিপোজিটরিতে ৪২টি ওয়ার্কফ্লো টেমপ্লেট রয়েছে
- **[SKILL টেমপ্লেট](SKILL.template.md)** — Claude, Gemini, Ollama ও Codex-ধাঁচের এজেন্টের জন্য LLM অপারেটিং নির্দেশনা

## আরও দেখুন: OpenClaw

জনপ্রিয় ওপেন-সোর্স AI সহকারী [OpenClaw](https://github.com/openclaw/openclaw)-এর তুলনায় BACH কেমন?

| | **BACH** | **OpenClaw** |
|---|---|---|
| **মূল লক্ষ্য** | LLM অপারেটিং সিস্টেম — গভীর স্বায়ত্তশাসন, কাঠামোবদ্ধ মেমরি, বহু-এজেন্ট অর্কেস্ট্রেশন | ব্যক্তিগত AI সহকারী — বিস্তৃত বার্তা গেটওয়ে, ভয়েস, সহচর অ্যাপ |
| **টুল/স্কিল** | 550+ টুল, 1870+ স্কিল, 42 ওয়ার্কফ্লো (স্থানীয়, নির্বাচিত) | সম্প্রদায়-চালিত স্কিল/প্লাগইন ইকোসিস্টেম; সাম্প্রতিক রিলিজে ম্যানিফেস্ট-ফার্স্ট প্লাগইন মেটাডেটা ও ইনস্টল নিরাপত্তায় জোর |
| **মেমরি** | ক্ষয়, দ্বন্দ্ব শনাক্তকরণ, সমন্বয়সহ ৬ ধরনের মেমরি (210+ DB টেবিল) | `AGENTS.md`, `TOOLS.md`, `USER.md`-এর মতো বুটস্ট্র্যাপ ফাইলসহ সেশন/রানটাইম কর্মক্ষেত্র এবং সংশ্লিষ্ট প্রসঙ্গ ফাইল |
| **এজেন্ট** | বস-বিশেষজ্ঞ অর্কেস্ট্রেশন (১১ বস এজেন্ট + ২২ বিশেষজ্ঞ), SharedMemory বাস | বহু সেশন/চ্যানেল-চালিত এজেন্ট রানটাইম |
| **বার্তাবিনিময়** | Telegram, ইমেল, WhatsApp (ব্রিজ ব্যবস্থা) | 20+ প্ল্যাটফর্ম (WhatsApp, Telegram, Slack, Discord, Signal, Teams, Matrix...) |
| **ইন্টারফেস** | CLI, Python API, PySide6 GUI, Web GUI, Telegram বট, Web Chat, সিস্টেম ট্রে | CLI, WebChat, macOS/iOS/Android অ্যাপ, ভয়েস |
| **MCP** | নিজস্ব MCP সার্ভার (FileCommander, CodeCommander) | নেটিভ MCP Registry |
| **প্রযুক্তি স্তর** | Python 3.10+, SQLite | TypeScript, Node.js 22+ |
| **লাইসেন্স** | MIT | MIT |

**সংক্ষেপে:** BACH গভীরতায় যায় (কাঠামোবদ্ধ মেমরি, স্বায়ত্তশাসিত এজেন্ট, শিডিউলার, 210+ DB টেবিল)। OpenClaw বিস্তৃতিতে যায় (20+ মেসেঞ্জার, নেটিভ অ্যাপ, ভয়েস, বড় সম্প্রদায়)। দুই দর্শন আলাদা এবং পরস্পর-পরিপূরক।

### প্রতিযোগী পর্যবেক্ষণ

8 অক্টোবর 2026 অনুযায়ী OpenClaw-এর সংস্করণ `v2026.9.8` (8 অক্টোবর 2026-এ প্রকাশিত, তার আগে `v2026.9.7`)। সাম্প্রতিক উন্নয়নে বহু-এজেন্ট উত্তর স্থিতিশীলতা, এজেন্টের মধ্যে সেশন বরাদ্দের অখণ্ডতা, একাধিক Codex/worker প্রসেসে মেমরি ব্যবহার কমানো, Windows স্টার্টআপ ও আপডেট পুনঃচেষ্টার দৃঢ়তা এবং ২০ ভাষায় নীরবতার সেটিং গুরুত্ব পেয়েছে। BACH-এর জন্য প্রাসঙ্গিক স্থাপত্যগত দিকগুলো হলো পারমাণবিক পুনরুদ্ধার ও আপডেট সীমা (`bach update apply` / `rollback` / `upgrade repair`, `distribution_releases` v3.14.0), তত্ত্বাবধানে রিস্টার্ট হস্তান্তর ও সেশন-চালু রাখার প্রসঙ্গ (OPS-RUN-001 / Task #1118), shell ছাড়া নিরাপদ নির্বাহ (`safe_exec.py` / PR #137) এবং স্থানীয় নিম্ন-কার্ডিনালিটি টেলিমেট্রি কাউন্টার (`system/core/telemetry.py` / Task #1315); মোবাইল/মেসেজিং গেটওয়ের বিস্তৃত সমতা BACH-এর মূল নকশার বাইরে।

BACH-এর ক্ষেত্রে, 8 অক্টোবরের পরিচর্যা ও উন্নয়ন পরীক্ষা main-এর রিপোজিটরি অবস্থা নিশ্চিত করে (origin/main থেকে fast-forward, PR #190–#253-সহ: নেটিভ সিকোয়েন্স ও marblerun worker fencing, শেয়ার্ড GUI v0.1.4, Astro স্থির সম্পদের অনুমতি-তালিকা, এজেন্ট ওয়ার্কশপ ও ব্লুপ্রিন্ট, জীবনযাত্রার রুটিন ও ক্যালেন্ডার, ডোমেইন ক্যাটালগ ম্যানিফেস্ট, মূল টাস্ক DB-এর salt lease contract v1 এবং CodeQL নিরাপত্তা সংশোধন)। সেশন জীবনচক্র ব্যবস্থাপনা সহযোগী Gemini-র জন্য সম্পূর্ণ ধারাবাহিকতা স্ন্যাপশটসহ নতুন সেশন (`session_20261008_162204`) শুরু করে। পরীক্ষার যাচাই স্যুট (`test_setup_handler.py`, `test_maintain_handler.py`, `test_db_guard_hook.py`, `test_explorer_provider_wiring.py`) সম্পূর্ণ সফল হয় (46.29 সেকেন্ডে 138/138)। Agent Doctor ডায়াগনস্টিক (`ati`, `entwickler`-এ 7/7 পরীক্ষা সফল, `ready: true`, `can_start: true`), স্টার্টআপ dry-run, Scheduler Doctor (7/7 পরীক্ষা সফল, 5টির মধ্যে 4টি কাজ সক্রিয়), 50/50 ব্যবহার-মামলা dry-run (100% ওয়ার্কফ্লোতে সংযুক্ত), ডকুমেন্টেশন সতেজতা (`Doc_Update_Report_2026-10-08_16-25.md`-এ 2,101 নথি পরীক্ষা, 30-দিনের প্রতিবেদন `2026-10_docs_report.md`), রেজিস্ট্রি স্বাস্থ্য (0টি করণীয় সমস্যা), টাস্ক-DB অডিট (29টি সামঞ্জস্যপূর্ণ কাজ), স্কিল স্বাস্থ্য (30/30 স্কিল, 10/10 এজেন্ট) এবং কার্যকরী মেমরি অডিট (189 এন্ট্রি, 0 মেয়াদোত্তীর্ণ) সম্পূর্ণ নিশ্চিত হয়। নতুন ব্যাকআপ `userdata_2026-10-08_162846.zip` তৈরি করা হয়।

## লাইসেন্স

MIT লাইসেন্স — বিস্তারিত জানতে [LICENSE](LICENSE) দেখুন।

## সহায়তা

- **সমস্যা:** [GitHub Issues](https://github.com/ellmos-ai/bach/issues)
- **আলোচনা:** [GitHub Discussions](https://github.com/ellmos-ai/bach/discussions)

---

## জার্মান সংস্করণ

BACH একটি টেক্সট-ভিত্তিক অপারেটিং সিস্টেম, যা বৃহৎ ভাষা মডেলকে (LLM) স্বয়ংক্রিয়ভাবে কাজ করতে, শিখতে ও সংগঠিত হতে সক্ষম করে।

সম্পূর্ণ জার্মান ডকুমেন্টেশন এখানে: **[README.de.md](README.de.md)**

---

*ellmos BACH v3.15.0 — LLM-এর জন্য টেক্সট-ভিত্তিক অপারেটিং সিস্টেম*

---

## দায়বদ্ধতা / দায়সীমা

এই প্রকল্প জার্মান দেওয়ানি আইনের (BGB) §§ 516 ও পরবর্তী ধারার অর্থে **বিনা পারিশ্রমিকের ওপেন-সোর্স দান**। **BGB § 521** অনুযায়ী লেখকের দায় ইচ্ছাকৃত কাজ ও গুরুতর অবহেলা পর্যন্ত সীমাবদ্ধ। নির্বাচিত লাইসেন্স অনুযায়ী GPL-3.0 / MIT / Apache-2.0-এর §§ 15–16-এ থাকা দায়বর্জনও প্রযোজ্য।

ব্যবহার সম্পূর্ণ নিজ দায়িত্বে। রক্ষণাবেক্ষণ বা প্রাপ্যতার কোনো প্রতিশ্রুতি নেই; ত্রুটিমুক্ততা বা নির্দিষ্ট কাজে উপযুক্ততার কোনো নিশ্চয়তা নেই।

এই প্রকল্প বিনা পারিশ্রমিকের ওপেন-সোর্স দান। দায় ইচ্ছাকৃত কাজ ও গুরুতর অবহেলা পর্যন্ত সীমিত (জার্মান দেওয়ানি আইনের § 521)। ব্যবহার নিজ দায়িত্বে। কোনো ওয়ারেন্টি, রক্ষণাবেক্ষণ প্রতিশ্রুতি বা নির্দিষ্ট কাজে উপযুক্ততার নিশ্চয়তা নেই।

## বহনযোগ্য এজেন্ট স্টার্টার ফাইল

`start/agents/windows/`-এ START, SYSTEM-AUDITOR, TICKET-MASTER, PINGPONG এবং MULTI-BOT `.bat` ফাইল রয়েছে; `start/agents/posix/` তাদের shell সংস্করণ দেয়। wheel এগুলো `share/ellmos-bach/starters/`-এ অন্তর্ভুক্ত করে। এগুলো বিদ্যমান TASKPLAN Startcenter এবং মডিউল ভূমিকা চুক্তিতে কাজ অর্পণ করে। আগে পর্যালোচিত TASKPLAN সংস্করণটি Startcenter ও ঐচ্ছিক ভূমিকা মডিউলসহ ইনস্টল করুন। এই ফাইল ব্যক্তিগত পাথ, অ্যাকাউন্ট, মডেল বা বিশ্বস্ত অটোমেশন সেট করে না। ইনস্টলেশনের সময় এগুলো ব্যাকগ্রাউন্ড কাজ নিবন্ধন বা শুরু করে না। ভূমিকা বেছে নিতে START চালান। PingPong-এর জন্য স্পষ্ট সিঙ্ক রুট ও নিজস্ব স্লট দরকার এবং এটি যাচাইকৃত Codex/Claude অ্যাডাপ্টার সমর্থন করে; MULTI-BOT সর্বসাধারণের githubbot-core প্যাকেজ ব্যবহার করে। প্রিভিউর জন্য `--dry-run --provider codex` দিন; মডিউল অনুপস্থিত হলে ইনস্টলেশন নির্দেশনা দেখা যাবে।
