# 🤖 HAYO AI Agent — وكيل ذكي خارق القدرات

وكيل ذكاء اصطناعي محلي يعمل على جهازك بصلاحيات كاملة — ينفذ كل شيء تطلبه منه بدقة.

## القدرات

| القدرة | التفاصيل |
|--------|----------|
| 🖥️ **النظام** | تنفيذ أوامر PowerShell و CMD، إدارة العمليات والخدمات، المهام المجدولة |
| 📁 **الملفات** | قراءة، كتابة، نسخ، نقل، بحث، تحميل، إنشاء مجلدات |
| 🌐 **المتصفح** | Chrome: تصفح، بحث، تحميل ملفات، ملء نماذج، لقطات شاشة |
| 🖱️ **سطح المكتب** | فتح أي تطبيق، لقطات شاشة، تحكم بالماوس والكيبورد |
| 📋 **الحافظة** | نسخ، لصق، إلحاق النصوص |
| 🌍 **الشبكة** | فحص الاتصال، DNS، Wi-Fi، منافذ TCP |
| 🔊 **الصوت** | تحكم بالمستوى، قراءة نص بصوت عالٍ، إشعارات |
| 🔧 **الإصلاح** | إصلاح مشاكل النظام، التسجيل، الخدمات |
| 🎵 **التحميل** | YouTube/أي موقع → MP3/MP4 عبر yt-dlp |
| 🔍 **Git** | عمليات على المستودعات المحلية |
| 🔌 **التكاملات** | GitHub, Google Drive, Telegram, Slack, Notion, Trello, Discord, Webhook |
| 🧩 **الإضافات** | نظام إضافات مرن — أنشئ أدواتك الخاصة |

## النماذج المدعومة

| النموذج | المزود | الموقع |
|---------|--------|--------|
| 🟦 **Gemini** | Google | [aistudio.google.com](https://aistudio.google.com/app/apikey) |
| 🟠 **Claude** | Anthropic | [console.anthropic.com](https://console.anthropic.com/) |
| 🟢 **ChatGPT** | OpenAI | [platform.openai.com](https://platform.openai.com/api-keys) |
| 🔵 **DeepSeek** | DeepSeek | [platform.deepseek.com](https://platform.deepseek.com/api_keys) |
| 🦙 **Ollama** | محلي مجاني | [ollama.com](https://ollama.com/download) |

يمكنك تغيير النموذج من الواجهة مباشرة بكتابة `/model google` أو `/model anthropic` أو `/model openai` أو `/model deepseek` أو `/model ollama`.

### استخدام Ollama (مجاني بالكامل!)

Ollama يشغّل نماذج الذكاء الاصطناعي محلياً على جهازك بدون الحاجة لمفتاح API أو دفع أي مال:

1. **ثبّت Ollama**: حمّله من [ollama.com/download](https://ollama.com/download)
2. **حمّل نموذجاً**: افتح Terminal واكتب:
   ```bash
   ollama pull dolphin3
   ```
3. **عدّل ملف `.env`**: غيّر `MODEL_PROVIDER=google` إلى:
   ```
   MODEL_PROVIDER=ollama
   OLLAMA_AGENT_MODEL=dolphin3
   OLLAMA_SUMMARIZER_MODEL=dolphin3
   ```
4. **شغّل الوكيل**: انقر مرتين على `START.bat`

| النموذج | الحجم | الوصف |
|---------|------|-------|
| `dolphin3` | 8B | Dolphin 3.0 Llama 3.1 (غير مقيد، function calling، موصى به) |
| `llama3.1` | 8B | متوازن وموصى به |
| `llama3.2` | 3B | أخف وأسرع |
| `mistral` | 7B | Mistral AI |
| `gemma2` | 9B | Google Gemma 2 |
| `qwen2.5` | 7B | Alibaba Qwen |
| `codellama` | 7B | متخصص بالبرمجة |

## مركز التكاملات 🔌

اربط الوكيل بخدمات خارجية مباشرة من الواجهة:

| الخدمة | الأيقونة | الأوامر |
|--------|---------|----------|
| **GitHub** | 🐙 | `/connect github` — ربط المستودعات |
| **Google Drive** | 📁 | `/connect gdrive` — ربط الملفات السحابية |
| **Telegram** | ✈️ | `/connect telegram` — ربط بوت تلغرام |
| **Slack** | 💬 | `/connect slack` — ربط قناة سلاك |
| **Notion** | 📝 | `/connect notion` — ربط قاعدة بيانات نوشن |
| **Trello** | 📋 | `/connect trello` — ربط لوحة تريلو |
| **Discord** | 🎮 | `/connect discord` — ربط خادم ديسكورد |
| **Webhook** | 🔗 | `/connect webhook` — ربط واجهة برمجة مخصصة |

### إضافة تكامل مخصص

```
/add-integration myapi https://api.example.com واجهة برمجة مخصصة
```

يمكنك ربط أي موقع أو تطبيق يدعم واجهة برمجة (API) أو Webhook.

## نظام الإضافات 🧩

أنشئ أدواتك الخاصة وأضفها للوكيل بسهولة:

1. أنشئ ملف `.py` في مجلد `plugins/`
2. عرّف الأدوات باستخدام `@tool`
3. صدّرها في قائمة `TOOLS`

```python
from langchain_core.tools import tool

PLUGIN_NAME = "My Plugin"
PLUGIN_DESCRIPTION = "وصف الإضافة"

@tool
def my_tool(query: str) -> str:
    """وصف الأداة."""
    return "النتيجة"

TOOLS = [my_tool]
```

الأوامر:
- `/plugins` — عرض الإضافات المحملة
- `/plugins reload` — إعادة تحميل الإضافات

## المعمارية

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  PLANNER    │───►│   WORKER    │───►│  REVIEWER   │
│ (يخطط)      │    │ (ينفذ)      │    │ (يراجع)     │
└─────────────┘    └─────▲───────┘    └─────┬───────┘
                         │                  │
                         └──────────────────┘
                              CONTINUE
```

- **LangGraph** كبنية أساسية للحالة والتوجيه
- **SQLite Checkpointer** لحفظ المحادثات بين تشغيلات الخادم
- **Human-in-the-Loop** للأوامر المدمرة و CAPTCHA — يتوقف الوكيل ويسأل
- **6 مزودين** — Google Gemini, Claude, ChatGPT, DeepSeek, Groq, Ollama (مجاني)

## التثبيت السريع

### الطريقة 1: بضغطة زر (الأسهل)
1. ضع المجلد `HAYO AI AGENT` في القرص `C:\`
2. عدّل ملف `.env` وأضف مفاتيح API الخاصة بك
3. انقر مرتين على **`START.bat`** — سيفعل كل شيء تلقائياً!

### الطريقة 2: يدوياً
```powershell
cd "C:\HAYO AI AGENT"

# 1) إنشاء البيئة الافتراضية
python -m venv venv
.\venv\Scripts\activate

# 2) تثبيت التبعيات
pip install -r requirements.txt

# 3) تثبيت متصفح Playwright
python -m playwright install chromium --with-deps

# 4) إعداد المفاتيح
copy .env.example .env
notepad .env
# أضف مفاتيح API الخاصة بك

# 5) تشغيل الوكيل
chainlit run app.py --port 8000
```

## التشغيل والإيقاف

| الإجراء | كيف |
|---------|-----|
| 🟢 **تشغيل** | انقر مرتين على `START.bat` |
| 🔴 **إيقاف** | انقر مرتين على `STOP.bat` أو اضغط `Ctrl+C` |

الواجهة تفتح تلقائياً على `http://localhost:8000`

## أمثلة طلبات

| الطلب | ما سيفعله الوكيل |
|-------|-------------------|
| "افتح Word واكتب فيه رسالة شكر" | open_app → keyboard_type → keyboard_hotkey('ctrl,s') |
| "حمّل أغنية عمرو دياب على سطح المكتب" | download_file('ytsearch:Amr Diab') |
| "ابحث في Google عن مشاريع Python وافتح أعلى نتيجة" | browser_open → browser_click |
| "اعرض معلومات النظام والذاكرة" | get_system_info → list_processes |
| "أصلح مشكلة الشبكة في جهازي" | get_network_info → ping_host → run_powershell |
| "اقرأ ملف report.docx من سطح المكتب" | read_file(path='C:\\Users\\...\\Desktop\\report.docx') |
| "أنسخ هذا النص إلى الحافظة" | clipboard_set(text='...') |
| "خفض صوت الجهاز إلى 30%" | volume_control(action='set', level=30) |

## الأوامر الخاصة

| الأمر | الوظيفة |
|-------|---------|
| `/model google` | تغيير النموذج إلى Google Gemini |
| `/model anthropic` | تغيير النموذج إلى Anthropic Claude |
| `/model openai` | تغيير النموذج إلى OpenAI ChatGPT |
| `/model deepseek` | تغيير النموذج إلى DeepSeek |
| `/model ollama` | تغيير النموذج إلى Ollama (مجاني محلي) |
| `/integrations` | عرض مركز التكاملات |
| `/connect <خدمة>` | ربط خدمة (github, gdrive, telegram...) |
| `/disconnect <خدمة>` | فصل خدمة |
| `/add-integration <اسم> <رابط>` | إضافة تكامل مخصص |
| `/plugins` | عرض الإضافات المحملة |
| `/plugins reload` | إعادة تحميل الإضافات |
| `/settings` | عرض الإعدادات الحالية |
| `/settings set <مفتاح> <قيمة>` | تغيير إعداد |
| `/tasks` | عرض سجل المهام المنفذة |
| `/tasks clear` | مسح سجل المهام |
| `/export` | تصدير المحادثة الحالية كملف JSON |
| `/screenshot` أو `لقطة شاشة` | أخذ لقطة شاشة لسطح المكتب |
| `أكمل` أو `continue` | استئناف المهمة السابقة |

## الأمان

الوكيل **يتوقف ويسألك** قبل تنفيذ هذه الأوامر:
- `Remove-Item -Recurse`, `rm -rf`, `format`
- `shutdown`, `Restart-Computer`
- `Set-ExecutionPolicy`, `reg delete`
- `Add-LocalGroupMember`, `New-LocalUser`

عند اكتشاف أمر خطير، يظهر زر **موافق/رفض** في الواجهة.

## هيكل المشروع

```
HAYO AI AGENT/
├── app.py                  # واجهة Chainlit الرسومية
├── main.py                 # واجهة CLI بديلة
├── config.py               # إعدادات مركزية
├── START.bat               # تشغيل بنقرة واحدة
├── STOP.bat                # إيقاف بنقرة واحدة
├── .env                    # مفاتيح API (لا ترفعه)
├── .env.example            # قالب الإعدادات
├── requirements.txt
│
├── agent/
│   ├── workflow.py          # تجميع LangGraph
│   ├── nodes.py             # PlannerNode + WorkerNode + ReviewerNode
│   └── graph.py             # shim للتوافق
│
├── core/
│   ├── state.py             # AgentState TypedDict
│   ├── safety.py            # فحص الأوامر المدمرة
│   ├── integrations.py      # 🔌 مركز التكاملات
│   ├── plugins.py           # 🧩 نظام الإضافات
│   └── task_history.py      # 📋 سجل المهام
│
├── plugins/                 # 🧩 مجلد الإضافات المخصصة
│   └── example_plugin.py    # إضافة مثال توضيحي
│
└── tools/
    ├── registry.py          # سجل موحد لجميع الأدوات
    ├── system_tools.py      # PowerShell, CMD, ملفات, بيئة
    ├── browser_tools.py     # Playwright: تصفح, نقر, ملء, لقطات
    ├── desktop_tools.py     # pyautogui: تطبيقات, ماوس, كيبورد
    ├── clipboard_tools.py   # حافظة Windows
    ├── process_tools.py     # عمليات, خدمات, مهام مجدولة
    ├── network_tools.py     # شبكة, DNS, Wi-Fi, منافذ
    ├── audio_tools.py       # صوت, إشعارات, قراءة نص
    ├── web_tools.py         # بحث ويب + تحميل (yt-dlp)
    ├── github_tools.py      # 🐙 أدوات GitHub
    ├── gdrive_tools.py      # 📁 أدوات Google Drive
    └── desktop_control.py   # توافق مع الإصدار السابق
```

## استكشاف الأخطاء

| مشكلة | الحل |
|-------|------|
| `GOOGLE_API_KEY is empty` | عدّل `.env` وضع المفتاح أو استخدم `MODEL_PROVIDER=ollama` للعمل بدون مفتاح |
| `playwright not installed` | `python -m playwright install chromium` |
| `ModuleNotFoundError` | `pip install -r requirements.txt` |
| الوكيل يدور بلا توقف | المشروع به حد `MAX_ITERATIONS=50` يُجبره على التوقف |
| المتصفح يفتح بدون كوكيز | أول مرة يفتح profile جديد. سجّل دخول ستحفظه `.browser_profile/` تلقائياً |
| Ollama لا يعمل | تأكد أن Ollama يعمل (`ollama serve`) وأنك حمّلت نموذجاً (`ollama pull llama3.1`) |
