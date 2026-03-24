import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.core.config import settings

logger = logging.getLogger(__name__)

RESET_PASSWORD_EMAIL_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Reset Your Password</title>
</head>

<body style="margin:0; padding:0; background-color:#f4f6f8; font-family:Arial, sans-serif;">

  <table width="100%" cellpadding="0" cellspacing="0" style="padding:15px;">
    <tr>
      <td align="center">

        <!-- Main Card -->
        <table width="100%" cellpadding="0" cellspacing="0" 
          style="max-width:500px; background:#ffffff; border-radius:12px; padding:25px; box-shadow:0 4px 12px rgba(0,0,0,0.08);">

          <!-- Header -->
          <tr>
            <td align="center" style="padding-bottom:15px;">
              <h2 style="margin:0; color:#2c3e50; font-size:22px;">
                  Password Reset Request
              </h2>
              <p style="margin:5px 0 0; color:#888; font-size:14px;">
                GTD Service Secure Access
              </p>
            </td>
          </tr>

          <!-- Message -->
          <tr>
            <td style="font-size:14px; color:#555; line-height:1.6; padding:10px 0;">
              We received a request to reset your password. Use the token below to complete the process.
              <br><br>
              <strong>Your Reset Token:</strong>
            </td>
          </tr>

          <!-- Token Card -->
          <tr>
            <td align="center" style="background:#f9fafb; padding:20px; border-radius:8px; font-size:24px; color:#4f46e5; border: 2px dashed #4f46e5; font-weight: bold; letter-spacing: 2px;">
              {{token}}
            </td>
          </tr>

          <!-- Instructions -->
          <tr>
            <td style="font-size:13px; color:#666; line-height:1.6; padding-top:20px;">
              This token will expire in 15 minutes. If you did not request this reset, you can safely ignore this email.
            </td>
          </tr>

          <!-- Button -->
          <tr>
            <td align="center" style="padding:25px 0;">
              <a href="{{reset_url}}"
                style="display:inline-block; background:#4f46e5; color:#ffffff; text-decoration:none;
                padding:12px 22px; font-size:14px; border-radius:6px; font-weight: bold;">
                Reset Password Online
              </a>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="text-align:center; font-size:12px; color:#999; padding-top:10px;">
              If you have any questions, just reply to this email.<br><br>
              © 2026 GTD Service. All rights reserved.
            </td>
          </tr>

        </table>

      </td>
    </tr>
  </table>

</body>
</html>
"""

CONFIRMATION_EMAIL_TEMPLATE = """
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Demo Confirmation</title>
</head>

<body style="margin:0; padding:0; background-color:#f4f6f8; font-family:Arial, sans-serif;">

  <table width="100%" cellpadding="0" cellspacing="0" style="padding:15px;">
    <tr>
      <td align="center">

        <!-- Main Card -->
        <table width="100%" cellpadding="0" cellspacing="0" 
          style="max-width:500px; background:#ffffff; border-radius:12px; padding:25px; box-shadow:0 4px 12px rgba(0,0,0,0.08);">

          <!-- Header -->
          <tr>
            <td align="center" style="padding-bottom:15px;">
              <h2 style="margin:0; color:#2c3e50; font-size:22px;">
                  Demo Confirmed
              </h2>
              <p style="margin:5px 0 0; color:#888; font-size:14px;">
                GTD Service
              </p>
            </td>
          </tr>

          <!-- Greeting -->
          <tr>
            <td style="font-size:15px; color:#333; padding:10px 0;">
              Hi <strong>{{name}}</strong>,
            </td>
          </tr>

          <!-- Message -->
          <tr>
            <td style="font-size:14px; color:#555; line-height:1.6;">
              Thank you for booking a demo with us. Your request has been submitted successfully.
              <br><br>
              Our team will contact you shortly to proceed further.
            </td>
          </tr>

          <!-- Divider -->
          <tr>
            <td style="padding:20px 0;">
              <hr style="border:none; border-top:1px solid #eee;">
            </td>
          </tr>

          <!-- Details Card -->
          <tr>
            <td style="background:#f9fafb; padding:15px; border-radius:8px; font-size:13px; color:#444;">
              <strong> Your Details</strong><br><br>

              <b>Name:</b> {{name}}<br>
              <b>Email:</b> {{email}}<br>
              <b>Product:</b> {{product}}<br>
              <b>Country:</b> {{country}}<br>
            </td>
          </tr>

          <!-- Button -->
          <tr>
            <td align="center" style="padding:25px 0;">
              <a href="https://gtdservice.com"
                style="display:inline-block; background:#4f46e5; color:#ffffff; text-decoration:none;
                padding:12px 22px; font-size:14px; border-radius:6px;">
                Visit Our Website
              </a>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="text-align:center; font-size:12px; color:#999; padding-top:10px;">
              If you have any questions, just reply to this email.<br><br>
              © 2026 GTD Service. All rights reserved.
            </td>
          </tr>

        </table>

      </td>
    </tr>
  </table>

</body>
</html>
"""

def send_confirmation_email(recipient_email: str, name: str, product: str = "General Inquiry", country: str = "Not Specified"):
    """
    Sends a styled HTML confirmation email to the lead.
    """
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.warning("SMTP credentials not configured. Skipping email.")
        return False

    try:
        # Prepare HTML body
        html_body = CONFIRMATION_EMAIL_TEMPLATE.replace("{{name}}", name)
        html_body = html_body.replace("{{email}}", recipient_email)
        html_body = html_body.replace("{{product}}", product or "General Inquiry")
        html_body = html_body.replace("{{country}}", country or "Not Specified")

        # Create message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Confirmation: Your Demo with {settings.SMTP_FROM_NAME}"
        msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
        msg["To"] = recipient_email

        # Attach HTML part
        msg.attach(MIMEText(html_body, "html"))

        # Connect and send
        if settings.SMTP_USE_SSL:
            server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT)
        else:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT)
            if settings.SMTP_USE_TLS:
                server.starttls()
        
        import re
        smtp_user = re.sub(r'\s+', '', settings.SMTP_USER)
        smtp_pass = re.sub(r'\s+', '', settings.SMTP_PASSWORD)
        
        server.login(smtp_user, smtp_pass)
        server.sendmail(settings.SMTP_FROM_EMAIL.strip(), recipient_email, msg.as_string())
        server.quit()

        logger.info(f"Confirmation email sent to {recipient_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send confirmation email to {recipient_email}: {e}")
        return False

def send_reset_email(recipient_email: str, token: str):
    """
    Sends a password reset email with the secure token.
    """
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.warning("SMTP credentials not configured. Skipping reset email.")
        return False

    try:
        # Build Reset URL (Frontend)
        # Assuming frontend is on standard location or configured in settings
        frontend_url = settings.FRONTEND_ORIGIN.split(',')[0].strip() if hasattr(settings, 'FRONTEND_ORIGIN') else "http://localhost:3000"
        reset_url = f"{frontend_url}/reset-password?token={token}"

        # Prepare HTML body
        html_body = RESET_PASSWORD_EMAIL_TEMPLATE.replace("{{token}}", token)
        html_body = html_body.replace("{{reset_url}}", reset_url)

        # Create message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"Password Reset: Secure Token for {settings.SMTP_FROM_NAME}"
        msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
        msg["To"] = recipient_email

        # Attach HTML part
        msg.attach(MIMEText(html_body, "html"))

        # Connect and send
        if settings.SMTP_USE_SSL:
            server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT)
        else:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT)
            if settings.SMTP_USE_TLS:
                server.starttls()
        
        # Clean credentials
        import re
        smtp_user = re.sub(r'\s+', '', settings.SMTP_USER)
        smtp_pass = re.sub(r'\s+', '', settings.SMTP_PASSWORD)
        
        server.login(smtp_user, smtp_pass)
        server.sendmail(settings.SMTP_FROM_EMAIL.strip(), recipient_email, msg.as_string())
        server.quit()

        logger.info(f"Password reset email sent to {recipient_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send reset email to {recipient_email}: {e}")
        return False
