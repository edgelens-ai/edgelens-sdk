package edgelens

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"

	"github.com/grafana/sobek"
	"go.k6.io/k6/js/common"
)

const productionHost = "api.edgelens.ai"

type capturedRequest struct {
	method string
	path   string
	auth   string
}

// recordServer answers every call like the sessions API and records it.
func recordServer(t *testing.T) (*httptest.Server, func() []capturedRequest) {
	t.Helper()
	var mu sync.Mutex
	var got []capturedRequest
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		got = append(got, capturedRequest{r.Method, r.URL.Path, r.Header.Get("Authorization")})
		mu.Unlock()
		switch {
		case r.Method == "POST" && r.URL.Path == "/v1/sessions":
			w.Write([]byte(`{"id":"sess_new","status":"flashing"}`))
		case r.Method == "DELETE":
			w.Write([]byte(`{"status":"released"}`))
		default:
			w.Write([]byte(`{"status":"ready"}`))
		}
	}))
	t.Cleanup(srv.Close)
	return srv, func() []capturedRequest {
		mu.Lock()
		defer mu.Unlock()
		return append([]capturedRequest(nil), got...)
	}
}

// hostRecorder wraps the default transport and records every host dialled,
// so a test can prove the production API was never contacted.
type hostRecorder struct {
	mu    sync.Mutex
	hosts []string
	next  http.RoundTripper
}

func (h *hostRecorder) RoundTrip(r *http.Request) (*http.Response, error) {
	h.mu.Lock()
	h.hosts = append(h.hosts, r.URL.Hostname())
	h.mu.Unlock()
	if r.URL.Hostname() == productionHost {
		return nil, &productionContacted{}
	}
	return h.next.RoundTrip(r)
}

type productionContacted struct{}

func (*productionContacted) Error() string { return "test refused a request to " + productionHost }

func recordHosts(t *testing.T) *hostRecorder {
	t.Helper()
	rec := &hostRecorder{next: http.DefaultTransport}
	http.DefaultTransport = rec
	t.Cleanup(func() { http.DefaultTransport = rec.next })
	return rec
}

func (h *hostRecorder) assertNoProduction(t *testing.T) {
	t.Helper()
	h.mu.Lock()
	defer h.mu.Unlock()
	for _, host := range h.hosts {
		if host == productionHost {
			t.Errorf("a request went to %s; hosts contacted: %v", productionHost, h.hosts)
			return
		}
	}
}

func TestResumeReleaseUsesConfiguredKeyAndBaseURL(t *testing.T) {
	srv, requests := recordServer(t)

	c, err := (&Module{}).Connect(ConnectOptions{APIKey: "key-123", BaseURL: srv.URL})
	if err != nil {
		t.Fatalf("Connect: %v", err)
	}
	s, err := c.Resume("sess_abc")
	if err != nil {
		t.Fatalf("Resume: %v", err)
	}
	if err := s.Release(); err != nil {
		t.Fatalf("Release: %v", err)
	}

	got := requests()
	want := []capturedRequest{{"DELETE", "/v1/sessions/sess_abc", "Bearer key-123"}}
	if len(got) != 1 || got[0] != want[0] {
		t.Fatalf("requests = %+v, want %+v", got, want)
	}
}

func TestResumeWithEmptyKeyFails(t *testing.T) {
	rec := recordHosts(t)

	if _, err := (&Module{}).Connect(ConnectOptions{}); err == nil ||
		!strings.Contains(err.Error(), "apiKey is required") {
		t.Errorf("Connect with no key: err = %v, want an apiKey-required error", err)
	}

	s, err := (&Client{baseURL: "http://127.0.0.1:1"}).Resume("sess_abc")
	if err == nil || !strings.Contains(err.Error(), "no apiKey") {
		t.Errorf("Resume with no key: err = %v, want a no-apiKey error", err)
	}
	if s != nil {
		t.Errorf("Resume with no key returned a session: %+v", s)
	}
	if len(rec.hosts) != 0 {
		t.Errorf("requests were sent without a key: %v", rec.hosts)
	}
}

func TestResumeRejectsEmptySessionID(t *testing.T) {
	c := &Client{apiKey: "k", baseURL: "http://127.0.0.1:1"}
	if _, err := c.Resume(""); err == nil {
		t.Error("Resume(\"\") returned no error")
	}
}

func TestResumeNeverContactsProductionURL(t *testing.T) {
	rec := recordHosts(t)
	srv, requests := recordServer(t)

	c, err := (&Module{}).Connect(ConnectOptions{APIKey: "key-123", BaseURL: srv.URL})
	if err != nil {
		t.Fatalf("Connect: %v", err)
	}
	created, err := c.CreateSession(CreateSessionOptions{})
	if err != nil {
		t.Fatalf("CreateSession: %v", err)
	}
	s, err := c.Resume(created.ID)
	if err != nil {
		t.Fatalf("Resume: %v", err)
	}
	if err := s.WaitReady(WaitReadyOptions{Timeout: 5, PollInterval: 0.1}); err != nil {
		t.Fatalf("WaitReady: %v", err)
	}
	if err := s.Release(); err != nil {
		t.Fatalf("Release: %v", err)
	}

	rec.assertNoProduction(t)
	for _, r := range requests() {
		if r.auth != "Bearer key-123" {
			t.Errorf("%s %s sent Authorization %q", r.method, r.path, r.auth)
		}
	}
	if got := requests(); got[len(got)-1] != (capturedRequest{"DELETE", "/v1/sessions/sess_new", "Bearer key-123"}) {
		t.Errorf("last request = %+v, want the release of sess_new", got[len(got)-1])
	}
}

// TestResumeFromJSTeardown runs the documented script shape through the JS
// runtime: one client at init scope, resumed by id in teardown().
func TestResumeFromJSTeardown(t *testing.T) {
	rec := recordHosts(t)
	srv, requests := recordServer(t)

	rt := sobek.New()
	rt.SetFieldNameMapper(common.FieldNameMapper{})
	if err := rt.Set("edgelens", &Module{}); err != nil {
		t.Fatal(err)
	}
	if err := rt.Set("__ENV", map[string]string{
		"EDGELENS_API_KEY": "key-js", "EDGELENS_BASE_URL": srv.URL,
	}); err != nil {
		t.Fatal(err)
	}
	_, err := rt.RunString(`
		const client = edgelens.connect({
			apiKey: __ENV.EDGELENS_API_KEY,
			baseUrl: __ENV.EDGELENS_BASE_URL,
		});
		function teardown(data) { client.resume(data.sessionId).release(); }
		teardown({ sessionId: "sess_js" });
	`)
	if err != nil {
		t.Fatalf("script: %v", err)
	}

	got := requests()
	want := capturedRequest{"DELETE", "/v1/sessions/sess_js", "Bearer key-js"}
	if len(got) != 1 || got[0] != want {
		t.Fatalf("requests = %+v, want [%+v]", got, want)
	}
	rec.assertNoProduction(t)

	if v, _ := rt.RunString(`typeof edgelens.resume`); v.String() != "undefined" {
		t.Errorf("edgelens.resume is %s; resume belongs on the client", v)
	}

	_, err = rt.RunString(`edgelens.connect({ apiKey: __ENV.EDGELENS_MISSING })`)
	if err == nil || !strings.Contains(err.Error(), "apiKey is required") {
		t.Errorf("connect with an unset key: err = %v, want an apiKey-required error", err)
	}
}
