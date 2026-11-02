# رفع مساعدة رغد أورجانكس الصوتية على Render

نفس الكود ونفس الـ `Dockerfile` اللي بنستخدمهم لـ Railway. ملف `render.yaml` بيخلي Render يعرف كل الإعدادات لحاله.

## قبل ما تبدأ

جهّز هدول (التفاصيل بملف `DEPLOY_RAILWAY.md`، الخطوة 2):
1. مفتاح OpenAI.
2. سطر TURN من حساب Metered (`PIPECAT_ICE_SERVERS`). Render كمان ما بيدعم UDP، فهاد ضروري.
3. (اختياري) كلمة سر للصفحة: ضيف `SITE_PASSWORD` من **Environment** بعد الرفع. بدونها أي حدا معه الرابط بيقدر يجرّب.

## الخطوات

1. سجّل على https://render.com بحساب GitHub.
2. اكبس **New +** واختار **Blueprint**.
3. اربط GitHub إذا طلب، واختار repo **CallCenter**.
4. Render رح يقرأ `render.yaml` ويطلب منك القيمتين:
   * `OPENAI_API_KEY`: مفتاح OpenAI
   * `PIPECAT_ICE_SERVERS`: سطر TURN
5. اكبس **Apply** أو **Deploy Blueprint**. أول بناء بياخد 5 لـ 10 دقايق.
6. افتح الخدمة **raghad-voice-assistant**. الرابط مكتوب فوق، زي `https://raghad-voice-assistant.onrender.com`.
7. افتح الرابط واعمل مكالمة. (إذا حطيت `SITE_PASSWORD`، اسم المستخدم `raghad`.)

## بالـ Logs لازم تشوف

* `Public mode: no SITE_PASSWORD set` (أو `Password protection is on` إذا حطيت كلمة سر)
* `Uvicorn running on http://0.0.0.0:...`

## ملاحظات الخطة المجانية

* **بينام:** إذا ما حدا فتح الرابط لفترة، السيرفر بينام. أول فتح بعدها بياخد حوالي دقيقة.
* **الذاكرة 512MB:** إذا شفت بالـ logs **Out of memory** أو السيرفر بيعيد تشغيل حاله، غيّر الخطة من **Settings → Instance Type** لـ 2GB.

## إذا صار في مشكلة

| المشكلة | الحل |
|---|---|
| البناء فشل | ابعت آخر 30 سطر من الـ Logs. |
| المكالمة بتعلق على "جاري الاتصال" | سطر TURN: تأكد إنه JSON صحيح وأول عنصر فيه `?transport=tcp`. |
| بدك تغيّر مفتاح أو كلمة سر | من **Environment** بالخدمة، وبعدين **Save, rebuild, and deploy**. |
