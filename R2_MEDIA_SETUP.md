# Keep uploaded images available on Render

Product and website photos are files, not database rows. PostgreSQL keeps their file names; Cloudflare R2 stores the image bytes so they remain available after the Render service restarts or deploys.

## Configure Cloudflare R2

1. Create a Cloudflare R2 bucket using the Standard storage class.
2. Create an R2 API token limited to **Object Read & Write** for this bucket. Copy its Access Key ID and Secret Access Key into your secret manager; do not commit or send them.
3. Copy the S3 API endpoint from the token page. It has the form `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`.
4. Enable public delivery for product images using an R2 custom domain. For a development site, an R2 public development URL can be used if enabled. Put only the hostname in `R2_PUBLIC_DOMAIN`, without `https://`.
5. Add these environment variables in Render's service Environment settings. Use the same names in local `.env` if you want local uploads to go to the same bucket.

```dotenv
R2_BUCKET_NAME=your-bucket-name
R2_ENDPOINT_URL=https://your-account-id.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=your-access-key-id
R2_SECRET_ACCESS_KEY=your-secret-access-key
R2_PUBLIC_DOMAIN=images.your-domain.example
```

`R2_PUBLIC_DOMAIN` is optional. Without it, Django creates signed URLs for a private bucket. For public storefront product images, configure a public hostname and set it here.

Once the variables are set, deploy the app. Django switches uploaded images to R2 automatically; static CSS and JavaScript remain on the existing static-file storage. No database migration is needed.

## Copy existing local uploads

To copy files under the project's `media/` folder while preserving their paths, configure the R2 variables locally and run:

```powershell
.\.venv\Scripts\python.exe manage.py migrate_local_media
```

The command leaves local files in place and skips any object already in the bucket. Files that only existed on Render's temporary filesystem must be uploaded again if they were lost during a restart or deploy.

Cloudflare's current R2 allowance includes 10 GB-month of Standard storage and monthly request allowances; storage beyond the allowance is billed, so it is scalable rather than unlimited. See [R2 pricing](https://developers.cloudflare.com/r2/pricing/) and the [R2 setup guide for django-storages](https://django-storages.readthedocs.io/en/latest/backends/s3_compatible/cloudflare-r2.html).
