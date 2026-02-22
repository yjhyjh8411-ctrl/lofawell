# LOFA Welfare Fund System Blueprint

## Overview
A web-based welfare fund management system for LOFA employees. It allows users to apply for various welfare benefits, check their status, and admins to manage applications.

## Project Structure
- **Backend:** Python (Flask) in `functions/app.py`.
- **Database:** Firebase Firestore.
- **Storage:** Firebase Storage for attachments.
- **Frontend:** HTML/CSS/JavaScript with Bootstrap 5.
- **Environment:** Firebase App Hosting / Cloud Functions.

## Implemented Features
- User Authentication (Signup/Login) with Employee ID.
- Welfare Application Forms (Scholarship, Housing, Medical, etc.).
- Image Compression: Server-side compression for image uploads (JPEG, PNG, WEBP) using Pillow.
- My Status page for tracking applications.
- Admin Dashboard for application review and Excel export.
- Security: Session management with secure cookies and cache control.
- **QR Code Integration:** Added a dynamic QR code to the login page for easy mobile access.
- **Site Content Management:** Added "Rules (Regulations)" and "Announcements" sections to the login page.
- **Personal Information Consent:** Added a mandatory "Personal Information Collection and Use Consent" section to all application forms and the signup page to comply with South Korean regulations.
- **Admin Settings Dashboard:** Admins can now update the Rules and Announcements directly from the Admin page, which updates the login page in real-time.

## Detailed Feature List
...

