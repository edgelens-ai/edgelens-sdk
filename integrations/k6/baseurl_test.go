package edgelens

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"testing"

	"github.com/grafana/sobek"
	"go.k6.io/k6/js/common"
)

// localServer is the ConnectOptions for an httptest server: http:// on
// loopback, which needs both overrides.
func localServer(key, baseURL string) ConnectOptions {
	allow := true
	return ConnectOptions{
		APIKey:               key,
		BaseURL:              baseURL,
		AllowInsecureBaseURL: true,
		AllowPrivateBaseURL:  &allow,
	}
}

// hostTable is core/testdata/base_url_hosts.json, shared with the Python
// and TypeScript suites so all three clients refuse the same hosts.
type hostTable struct {
	Refused []string `json:"refused"`
	Private []string `json:"private"`
	Public  []string `json:"public"`
}

func loadHostTable(t *testing.T) hostTable {
	t.Helper()
	raw, err := os.ReadFile("../../core/testdata/base_url_hosts.json")
	if err != nil {
		t.Fatalf("read shared host table: %v", err)
	}
	var h hostTable
	if err := json.Unmarshal(raw, &h); err != nil {
		t.Fatalf("parse shared host table: %v", err)
	}
	if len(h.Refused) == 0 || len(h.Private) == 0 || len(h.Public) == 0 {
		t.Fatalf("shared host table has an empty section: %+v", h)
	}
	return h
}

func connect(baseURL string, allowPrivate *bool) error {
	_, err := (&Module{}).Connect(ConnectOptions{
		APIKey: "k", BaseURL: baseURL, AllowPrivateBaseURL: allowPrivate,
	})
	return err
}

func TestConnectSharedHostTable(t *testing.T) {
	t.Setenv("EDGELENS_ALLOW_PRIVATE_BASE_URL", "")
	h := loadHostTable(t)
	yes, no := true, false

	for _, host := range h.Refused {
		u := "https://" + host + "/"
		for _, allow := range []*bool{nil, &no, &yes} {
			err := connect(u, allow)
			if err == nil || !strings.Contains(err.Error(), "link-local/reserved") {
				t.Errorf("Connect(%s, allowPrivate=%v): err = %v, want a refusal", u, allow, err)
			}
		}
	}
	for _, host := range h.Private {
		u := "https://" + host + "/"
		if err := connect(u, nil); err == nil || !strings.Contains(err.Error(), "private/loopback") {
			t.Errorf("Connect(%s): err = %v, want a private-address refusal", u, err)
		}
		if err := connect(u, &yes); err != nil {
			t.Errorf("Connect(%s, allowPrivateBaseUrl): %v", u, err)
		}
	}
	for _, host := range h.Public {
		u := "https://" + host + "/"
		if err := connect(u, nil); err != nil {
			t.Errorf("Connect(%s): %v", u, err)
		}
	}
}

func TestConnectPrivateOverrideFromEnv(t *testing.T) {
	no := false
	for _, v := range []string{"1", "true", "YES", " on "} {
		t.Setenv("EDGELENS_ALLOW_PRIVATE_BASE_URL", v)
		if err := connect("https://10.0.0.1", nil); err != nil {
			t.Errorf("env %q: %v", v, err)
		}
		if err := connect("https://169.254.169.254", nil); err == nil {
			t.Errorf("env %q relaxed the metadata address", v)
		}
		if err := connect("https://10.0.0.1", &no); err == nil {
			t.Errorf("env %q overrode an explicit allowPrivateBaseUrl: false", v)
		}
	}
	for _, v := range []string{"", "0", "false", "no", "off", "2"} {
		t.Setenv("EDGELENS_ALLOW_PRIVATE_BASE_URL", v)
		if err := connect("https://10.0.0.1", nil); err == nil {
			t.Errorf("env %q allowed a private host", v)
		}
	}
}

func TestConnectSchemes(t *testing.T) {
	t.Setenv("EDGELENS_ALLOW_PRIVATE_BASE_URL", "")
	if _, err := (&Module{}).Connect(ConnectOptions{APIKey: "k", BaseURL: "http://api.edgelens.ai"}); err == nil ||
		!strings.Contains(err.Error(), "http://") {
		t.Errorf("http:// baseUrl: err = %v, want a cleartext refusal", err)
	}
	if _, err := (&Module{}).Connect(ConnectOptions{
		APIKey: "k", BaseURL: "http://api.edgelens.ai", AllowInsecureBaseURL: true,
	}); err != nil {
		t.Errorf("http:// with allowInsecureBaseUrl: %v", err)
	}
	for _, u := range []string{"http://169.254.169.254", "http://10.0.0.1", "http://[fd00:ec2::254]"} {
		if _, err := (&Module{}).Connect(ConnectOptions{
			APIKey: "k", BaseURL: u, AllowInsecureBaseURL: true,
		}); err == nil {
			t.Errorf("allowInsecureBaseUrl alone relaxed the host check for %s", u)
		}
	}
	for _, u := range []string{"file:///etc/passwd", "gopher://evil", "ws://x", "api.edgelens.ai"} {
		if err := connect(u, nil); err == nil {
			t.Errorf("Connect(%s) accepted a non-http scheme", u)
		}
	}
	if err := connect("https://", nil); err == nil {
		t.Error("Connect accepted a baseUrl with no host")
	}
}

func TestConnectDefaultAndTrailingSlashes(t *testing.T) {
	c, err := (&Module{}).Connect(ConnectOptions{APIKey: "k"})
	if err != nil || c.baseURL != "https://api.edgelens.ai" {
		t.Fatalf("default baseUrl: %v, %q", err, c.baseURL)
	}
	c, err = (&Module{}).Connect(ConnectOptions{APIKey: "k", BaseURL: "https://api.edgelens.ai" + strings.Repeat("/", 4096)})
	if err != nil || c.baseURL != "https://api.edgelens.ai" {
		t.Fatalf("trailing slashes: %v, %q", err, c.baseURL)
	}
}

func TestConnectRefusalFromJS(t *testing.T) {
	t.Setenv("EDGELENS_ALLOW_PRIVATE_BASE_URL", "1")
	rt := sobek.New()
	rt.SetFieldNameMapper(common.FieldNameMapper{})
	if err := rt.Set("edgelens", &Module{}); err != nil {
		t.Fatal(err)
	}
	_, err := rt.RunString(`edgelens.connect({ apiKey: "k", baseUrl: "https://10.0.0.1", allowPrivateBaseUrl: false })`)
	if err == nil || !strings.Contains(err.Error(), "private/loopback") {
		t.Errorf("explicit allowPrivateBaseUrl: false from JS: err = %v, want a refusal", err)
	}
	if _, err := rt.RunString(`edgelens.connect({ apiKey: "k", baseUrl: "https://10.0.0.1" })`); err != nil {
		t.Errorf("unset allowPrivateBaseUrl from JS should fall back to the env: %v", err)
	}
	_, err = rt.RunString(`edgelens.connect({ apiKey: "k", baseUrl: "https://169.254.169.254", allowPrivateBaseUrl: true })`)
	if err == nil || !strings.Contains(err.Error(), "link-local/reserved") {
		t.Errorf("metadata address from JS: err = %v, want a refusal", err)
	}
}

// pathServer records the escaped request path of every call.
func pathServer(t *testing.T) (*httptest.Server, func() []string) {
	t.Helper()
	var mu sync.Mutex
	var got []string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		got = append(got, r.Method+" "+r.URL.EscapedPath()+"|"+r.URL.RawQuery)
		mu.Unlock()
		w.Write([]byte(`{"status":"ready"}`))
	}))
	t.Cleanup(srv.Close)
	return srv, func() []string {
		mu.Lock()
		defer mu.Unlock()
		return append([]string(nil), got...)
	}
}

func TestSessionIDIsSentPercentEncoded(t *testing.T) {
	cases := []struct{ id, enc string }{
		{"../accounts/me/keys", "..%2Faccounts%2Fme%2Fkeys"},
		{"sess/../../admin", "sess%2F..%2F..%2Fadmin"},
		{"sess?admin=1", "sess%3Fadmin=1"},
		{"sess#frag", "sess%23frag"},
		{"sess%2F", "sess%252F"},
	}
	for _, tc := range cases {
		srv, paths := pathServer(t)
		c, err := (&Module{}).Connect(localServer("k", srv.URL))
		if err != nil {
			t.Fatalf("Connect: %v", err)
		}
		s, err := c.Resume(tc.id)
		if err != nil {
			t.Fatalf("Resume(%q): %v", tc.id, err)
		}
		if err := s.WaitReady(WaitReadyOptions{Timeout: 5}); err != nil {
			t.Fatalf("WaitReady(%q): %v", tc.id, err)
		}
		if _, err := s.Device().Exec("true", ExecOptions{}); err != nil {
			t.Fatalf("Exec(%q): %v", tc.id, err)
		}
		if err := s.Device().Inference().Start(); err != nil {
			t.Fatalf("Inference.Start(%q): %v", tc.id, err)
		}
		if err := s.Device().Deploy(DeployOptions{Model: DeployFile{Name: "m", Data: []byte("x")}}); err != nil {
			t.Fatalf("Deploy(%q): %v", tc.id, err)
		}
		if err := s.Release(); err != nil {
			t.Fatalf("Release(%q): %v", tc.id, err)
		}
		p := "/v1/sessions/" + tc.enc
		want := []string{
			"GET " + p + "|",
			"POST " + p + "/exec|",
			"POST " + p + "/inference/start|",
			"POST " + p + "/deploy|",
			"DELETE " + p + "|",
		}
		got := paths()
		if strings.Join(got, "\n") != strings.Join(want, "\n") {
			t.Errorf("id %q:\n got  %v\n want %v", tc.id, got, want)
		}
	}
}

func TestDotSessionIDsAreRefused(t *testing.T) {
	srv, paths := pathServer(t)
	c, err := (&Module{}).Connect(localServer("k", srv.URL))
	if err != nil {
		t.Fatalf("Connect: %v", err)
	}
	for _, id := range []string{".", ".."} {
		s, err := c.Resume(id)
		if err != nil {
			t.Fatalf("Resume(%q): %v", id, err)
		}
		if err := s.Release(); err == nil {
			t.Errorf("Release with id %q returned no error", id)
		}
		if _, err := s.Device().Inference().Stats(); err == nil {
			t.Errorf("Stats with id %q returned no error", id)
		}
	}
	if got := paths(); len(got) != 0 {
		t.Errorf("requests were sent for a dot id: %v", got)
	}
}
