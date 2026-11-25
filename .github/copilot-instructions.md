# AERIAL ELECTRONICS workspace instructions

- Project: Django e-commerce storefront and staff dashboard
- Payment preference: MTN Mobile Money only
- Business: Aerial Electronics, Kigali, Rwanda
- CEO: Joseph Byiringiro
- Preserve separate customer and protected admin experiences
- Use PostgreSQL in production and SQLite for local development
- Do not claim payment success without provider confirmation; integrate the MTN API with server-side callbacks before production
- Keep secret keys and provider credentials in environment variables
