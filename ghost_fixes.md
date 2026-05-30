# Futher ghost debug needed for admin login ....

2. Use this Ghost block in Caddy
@ghost host choukalos.com
handle @ghost {
	reverse_proxy http://ghost-blog:2368 {
		header_up Host {host}
		header_up X-Forwarded-Host {host}
		header_up X-Forwarded-Proto https
		header_up X-Forwarded-Port 443
		header_up X-Real-IP {remote_host}
	}
}
I’d remove this line:
header_up X-Forwarded-For {remote_host}
Caddy already handles X-Forwarded-For; manually setting it can be counterproductive.
3. Clear all browser site data
Not just cookies. Clear all site data for:
choukalos.com
www.choukalos.com
Then reopen:
https://choukalos.com/ghost/
4. Check Cloudflare caching
In Cloudflare, make sure you are not caching:
/ghost/*
/ghost/api/*
Add a cache rule: Bypass cache for:
URI Path starts with /ghost
5. Check browser DevTools
On login, look at the Network tab. The login response should include a Set-Cookie header for Ghost admin. Then the next request to:
/ghost/api/admin/users/me/?include=roles
must include a Cookie request header.
If Set-Cookie appears but the next request has no Cookie, it’s browser/domain/scheme/cookie policy.
If Set-Cookie never appears, Ghost still thinks the request context is wrong.

