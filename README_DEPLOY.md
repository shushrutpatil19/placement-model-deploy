# Placement Success Predictor — Render Deployment

## 🚀 Deploying on Render

1. Create a free account at [Render.com](https://render.com).
2. Push this folder to a GitHub repository.
3. In Render Dashboard → **New → Web Service** → Connect your repo.
4. Build Command:
   ```
   pip install -r requirements.txt
   ```
5. Start Command:
   ```
   gunicorn app:app
   ```
6. Add Environment Variables:
   ```
   SECRET_KEY=your_secret
   MAIL_USERNAME=your_gmail@gmail.com
   MAIL_PASSWORD=your_app_password
   MAIL_SERVER=smtp.gmail.com
   MAIL_PORT=587
   MAIL_USE_TLS=True
   ```
   *(Optional)*
   ```
   AI_PROVIDER=openai
   AI_API_KEY=sk-...
   ```
7. Click **Deploy**.
8. Your site will go live at a Render URL like:
   `https://placement-success.onrender.com`
