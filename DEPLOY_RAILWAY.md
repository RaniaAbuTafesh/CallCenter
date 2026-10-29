# رفع مساعدة رغد أورجانكس الصوتية على Railway

## شو في بهالمجلد

| الملف | شو بيعمل |
|---|---|
| `demo_bot.py` | البوت. نفس اللي عندك، ومضاف عليه 3 أشياء للسيرفر: فحص صحة، إعدادات TURN للصفحة، وكلمة سر اختيارية. |
| `raghad_organics_knowledge.txt` | معلومات رغد أورجانكس اللي البوت بيجاوب منها. |
| `raghad_ui/` | الصفحة المصممة. صارت تجيب إعدادات TURN من البوت قبل الاتصال. |
| `requirements.txt` | Pipecat بنفس النسخة اللي شغّالة عندك (commit 6a68835). |
| `Dockerfile` | طريقة بناء السيرفر على Railway. |
| `railway.json` | إعدادات Railway (البناء بالـ Dockerfile، وفحص الصحة على `/healthz`). |
| `.env.example` | أسماء المتغيرات اللي لازم تحطها على Railway، مع مثال. |
| `.gitignore` | بيمنع رفع ملف `.env` اللي فيه مفتاحك على GitHub. |

## ليش في خطوة TURN؟

Railway بيستقبل بس اتصالات ويب (HTTP/TCP) وما بيدعم UDP. الصوت بالـ WebRTC بيحتاج UDP، فبدون TURN الصفحة رح تفتح، بس المكالمة رح تعلق على "جاري الاتصال". سيرفر TURN بيمرّر الصوت عن طريق اتصال TCP عادي.

---

## الخطوة 1: جرّب على جهازك أول (5 دقايق)

هالخطوة بتتأكد إن التعديلات الجديدة شغّالة قبل ما ترفع أي شي.

1. انسخ ملف `.env` من `Desktop\pipecat\pipecat\` لجوّا مجلد `railway-deploy`. ما رح ينرفع على GitHub، لأن `.gitignore` بيمنعه.
2. افتح PowerShell بمجلد `railway-deploy` وشغّل:
   ```powershell
   $env:DEMO_PASSWORD = "test123"
   ..\pipecat\.venv\Scripts\python.exe demo_bot.py -t webrtc
   ```
3. افتح `http://localhost:7860/`. لازم يطلب منك اسم مستخدم وكلمة سر: اكتب `raghad` و `test123`.
4. اعمل مكالمة وتأكد إنها شغّالة. بعدين طفّيها بـ Ctrl+C.

## الخطوة 2: حساب TURN مجاني على Metered

1. سجّل على https://www.metered.ca واختار **TURN Server**. الخطة المجانية فيها 20 جيجا بالشهر، وهاد بيكفي لساعات كثير من المكالمات.
2. من لوحة التحكم افتح **TURN Server → Credentials** (أو "Add Credential" إذا ما في).
3. انسخ الـ **Username** والـ **Credential** (كلمة السر).
4. افتح `.env.example`، وانسخ سطر `PIPECAT_ICE_SERVERS`، وبدّل `YOUR_USERNAME` و `YOUR_CREDENTIAL` بقيمك، بكل الأماكن.
   * **مهم:** خلّي أول عنصر بالقائمة هو `turn:...:80?transport=tcp`. البوت على السيرفر بيستخدم أول عنوان TURN بس.
   * إذا لوحة Metered بتعطيك عناوين مختلفة عن اللي بالمثال، استخدم عناوينهم، بس خلّي واحد فيه `?transport=tcp` بالأول.

## الخطوة 3: ارفع المجلد على GitHub

1. اعمل حساب على https://github.com إذا ما عندك.
2. اعمل **New repository**، سمّيه مثلاً `raghad-voice-assistant`، واختار **Private**.
3. اكبس **uploading an existing file**، واسحب كل محتويات مجلد `railway-deploy`، بما فيها مجلد `raghad_ui`.
   * **لا ترفع ملف `.env`**، لأن فيه مفتاح OpenAI. إذا ظهر بالقائمة، احذفه قبل ما تكبس Commit.
4. اكبس **Commit changes**.

## الخطوة 4: أنشئ المشروع على Railway

1. ادخل على https://railway.com وسجّل دخول بحساب GitHub.
2. **New Project → Deploy from GitHub repo**، واختار `raghad-voice-assistant`. إذا طلب صلاحية الوصول للـ repo، اسمحله.
3. Railway رح يلاقي `Dockerfile` و `railway.json` ويبلّش البناء لحاله. أول بناء بياخد 5 لـ 10 دقايق.

## الخطوة 5: المتغيرات (Variables)

بالخدمة على Railway افتح تبويب **Variables** وضيف:

| الاسم | القيمة |
|---|---|
| `OPENAI_API_KEY` | مفتاح OpenAI تبعك |
| `PIPECAT_ICE_SERVERS` | السطر اللي جهّزته بالخطوة 2 (من بعد `=`) |
| `DEMO_PASSWORD` | كلمة سر للصفحة، **بأحرف إنجليزية وأرقام بس** |

بعد ما تحفظها، Railway رح يعيد التشغيل لحاله.

## الخطوة 6: رابط عام

1. افتح **Settings → Networking → Generate Domain**.
2. إذا سألك عن البورت (Port)، شوف بالـ **Deploy Logs** سطر `Uvicorn running on http://0.0.0.0:XXXX` واكتب نفس الرقم.
3. رح يعطيك رابط زي `https://raghad-voice-assistant-production.up.railway.app`.

## الخطوة 7: جرّب

1. افتح الرابط واكتب اسم المستخدم `raghad` وكلمة السر اللي حطيتها.
2. اكبس "ابدأ المكالمة" واسمح للميكروفون.
3. بالـ **Deploy Logs** لازم تشوف "Browser connected" أو "Client connected".

---

## إذا صار في مشكلة

| المشكلة | الحل |
|---|---|
| المكالمة بتعلق على "جاري الاتصال" | غالباً TURN. تأكد إن `PIPECAT_ICE_SERVERS` JSON صحيح (أقواس وفواصل)، والقيم بدون مسافات، وأول عنصر فيه `?transport=tcp`. |
| البناء فشل (Build failed) | افتح **Build Logs** وابعتلي آخر 30 سطر. |
| "OPENAI_API_KEY is missing" بالـ logs | المتغير مش مضاف، أو اسمه مكتوب غلط. |
| الصفحة بتضل تطلب كلمة السر | تأكد من اسم المستخدم `raghad`، وإن كلمة السر بالإنجليزي. |
| البوت ما بيرد أو في خطأ من OpenAI | تأكد إن بحسابك رصيد، وإن المفتاح شغّال. |

## التكلفة والأمان

* **Railway:** في فترة تجربة، وبعدها بتحتاج خطة مدفوعة (Hobby). شوف الأسعار الحالية على موقعهم.
* **OpenAI:** كل مكالمة بتكلّف حسب الاستخدام. حط حد للصرف من **OpenAI → Settings → Limits**.
* **كلمة السر:** إذا ما حطيت `DEMO_PASSWORD`، أي حدا معه الرابط بيقدر يحكي مع البوت على حسابك.
* **ما تنشر المفاتيح:** مفتاح OpenAI وبيانات TURN بس على Railway، مش على GitHub ولا بالشات.

## تحديث البوت بعدين

عدّل الملفات وارفعها على نفس الـ repo بـ GitHub (Upload files وبدّل القديمة). Railway رح يعيد البناء والتشغيل لحاله.
