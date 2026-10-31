package edgelens

import (
	"errors"
	"fmt"
	"net/netip"
	"net/url"
	"os"
	"strconv"
	"strings"
)

// The baseUrl host denylist, the same tables as the Python and TypeScript
// clients; all three suites run the shared cases in
// core/testdata/base_url_hosts.json.
//
// Refused even with the private override: link-local, multicast,
// unspecified, reserved, and the IPv6 instance metadata address.
var (
	v4Refused = prefixes("169.254.0.0/16", "224.0.0.0/4", "0.0.0.0/32", "240.0.0.0/4")
	v6Refused = prefixes(
		"fe80::/10", "ff00::/8", "::/128", "fd00:ec2::254/128",
		"::/8", "100::/8", "200::/7", "400::/6", "800::/5", "1000::/4", "4000::/3",
		"6000::/3", "8000::/3", "a000::/3", "c000::/3", "e000::/4", "f000::/5",
		"f800::/6", "fe00::/9",
	)
	// Refused unless the private override is set: loopback, private-use,
	// shared address space and the special-purpose blocks.
	v4Private = prefixes(
		"0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "172.16.0.0/12",
		"192.0.0.0/24", "192.0.0.170/31", "192.0.2.0/24", "192.168.0.0/16",
		"198.18.0.0/15", "198.51.100.0/24", "203.0.113.0/24",
	)
	v4PrivateExcept = prefixes("192.0.0.9/32", "192.0.0.10/32")
	v6Private       = prefixes(
		"::1/128", "64:ff9b:1::/48", "100::/64", "2001::/23", "2001:db8::/32",
		"2002::/16", "3fff::/20", "fc00::/7",
	)
	v6PrivateExcept = prefixes(
		"2001:1::1/128", "2001:1::2/128", "2001:3::/32", "2001:4:112::/48",
		"2001:20::/28", "2001:30::/28",
	)
)

func prefixes(cidrs ...string) []netip.Prefix {
	out := make([]netip.Prefix, len(cidrs))
	for i, c := range cidrs {
		out[i] = netip.MustParsePrefix(c)
	}
	return out
}

func inAny(ip netip.Addr, nets []netip.Prefix) bool {
	for _, n := range nets {
		if n.Contains(ip) {
			return true
		}
	}
	return false
}

// parseLegacyIPv4 reads the inet_aton forms a resolver accepts and a
// WHATWG URL parser normalises (127.1, 2130706433, 0x7f000001,
// 017700000001), so they cannot pass as DNS names.
func parseLegacyIPv4(host string) (netip.Addr, bool) {
	parts := strings.Split(host, ".")
	if len(parts) > 4 {
		return netip.Addr{}, false
	}
	vals := make([]uint64, len(parts))
	for i, p := range parts {
		if p == "" {
			return netip.Addr{}, false
		}
		base, digits := 10, p
		switch {
		case strings.HasPrefix(p, "0x"):
			base, digits = 16, p[2:]
		case len(p) > 1 && p[0] == '0':
			base, digits = 8, p[1:]
		}
		if digits == "" && base == 16 {
			digits = "0"
		}
		v, err := strconv.ParseUint(digits, base, 32)
		if err != nil {
			return netip.Addr{}, false
		}
		vals[i] = v
	}
	last := len(vals) - 1
	for _, v := range vals[:last] {
		if v > 255 {
			return netip.Addr{}, false
		}
	}
	if vals[last] >= 1<<(8*uint(4-last)) {
		return netip.Addr{}, false
	}
	var n uint64
	for i, v := range vals[:last] {
		n |= v << (8 * uint(3-i))
	}
	n |= vals[last]
	return netip.AddrFrom4([4]byte{byte(n >> 24), byte(n >> 16), byte(n >> 8), byte(n)}), true
}

// classifyHost returns "public", "private" or "refused" for a URL
// hostname, read as written: a DNS name is not resolved.
func classifyHost(hostname string) string {
	host := strings.ToLower(hostname)
	host = strings.TrimSuffix(strings.TrimPrefix(host, "["), "]")
	host = strings.TrimSuffix(host, ".")
	if host == "localhost" || strings.HasSuffix(host, ".localhost") {
		return "private"
	}
	ip, err := netip.ParseAddr(host)
	if err != nil {
		var ok bool
		if ip, ok = parseLegacyIPv4(host); !ok {
			return "public"
		}
	}
	ip = ip.WithZone("").Unmap()
	refused, private, except := v6Refused, v6Private, v6PrivateExcept
	if ip.Is4() {
		refused, private, except = v4Refused, v4Private, v4PrivateExcept
	}
	if inAny(ip, refused) {
		return "refused"
	}
	if inAny(ip, private) && !inAny(ip, except) {
		return "private"
	}
	return "public"
}

// allowPrivateFromEnv reads EDGELENS_ALLOW_PRIVATE_BASE_URL the way the
// Python and TypeScript clients do.
func allowPrivateFromEnv() bool {
	switch strings.ToLower(strings.TrimSpace(os.Getenv("EDGELENS_ALLOW_PRIVATE_BASE_URL"))) {
	case "1", "true", "yes", "on":
		return true
	}
	return false
}

// validateBaseURL refuses a base URL the Bearer token must not be sent
// to, and returns it without trailing slashes.
func validateBaseURL(raw string, allowInsecure, allowPrivate bool) (string, error) {
	if raw == "" {
		return "", errors.New("baseUrl is empty")
	}
	u, err := url.Parse(raw)
	if err != nil {
		return "", fmt.Errorf("baseUrl is not a valid URL: %s", raw)
	}
	scheme := strings.ToLower(u.Scheme)
	if scheme != "https" && scheme != "http" {
		return "", fmt.Errorf("baseUrl scheme %q not allowed (use http or https)", u.Scheme)
	}
	if scheme == "http" && !allowInsecure {
		return "", errors.New("baseUrl uses http://, so the Bearer token would be sent in " +
			"cleartext. Pass allowInsecureBaseUrl: true if this is a local dev loop.")
	}
	host := u.Hostname()
	if host == "" {
		return "", errors.New("baseUrl is missing a host")
	}
	switch classifyHost(host) {
	case "refused":
		return "", fmt.Errorf("baseUrl host %s is a link-local/reserved address; "+
			"refusing to send the Bearer token there.", host)
	case "private":
		if !allowPrivate {
			return "", fmt.Errorf("baseUrl host %s is a private/loopback address. If this "+
				"is a server you control, such as a local test server, pass "+
				"allowPrivateBaseUrl: true or set EDGELENS_ALLOW_PRIVATE_BASE_URL=1.", host)
		}
	}
	return strings.TrimRight(raw, "/"), nil
}

// sessionPath is /v1/sessions/<id><suffix> with the id as one opaque path
// segment. "." and ".." are refused: they are dot segments even escaped.
func sessionPath(id, suffix string) (string, error) {
	if id == "" || id == "." || id == ".." {
		return "", fmt.Errorf("invalid session id %q", id)
	}
	return "/v1/sessions/" + url.PathEscape(id) + suffix, nil
}
