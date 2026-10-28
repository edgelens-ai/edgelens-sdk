package edgelens

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/grafana/sobek"
	"go.k6.io/k6/js/common"
)

// fakeServer stands in for the EdgeLens API so we can run the client
// surface end-to-end without real hardware.
func fakeServer(t *testing.T, sessions map[string]string) *httptest.Server {
	t.Helper()
	mux := http.NewServeMux()
	mux.HandleFunc("/v1/sessions", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "POST" {
			http.Error(w, "method", 405)
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]any{
			"id": "sess_fake1", "status": "flashing",
		})
	})
	mux.HandleFunc("/v1/sessions/", func(w http.ResponseWriter, r *http.Request) {
		id := strings.TrimPrefix(r.URL.Path, "/v1/sessions/")
		switch {
		case strings.HasSuffix(id, "/inference/start"):
			w.Write([]byte(`{"state":"running"}`))
		case strings.HasSuffix(id, "/inference/results"):
			_ = json.NewEncoder(w).Encode(Stats{
				FPS:            PercentileStats{Avg: 17.4, P95: 18.9},
				LatencyMS:      PercentileStats{Avg: 55, P95: 75, P99: 92},
				DetectionCount: 42,
				DurationS:      10,
			})
		case strings.HasSuffix(id, "/deploy"):
			w.Write([]byte(`{"success":true}`))
		case strings.HasSuffix(id, "/exec"):
			_ = json.NewEncoder(w).Encode(ExecResult{Stdout: "ok", ExitCode: 0})
		case r.Method == "DELETE":
			_ = json.NewEncoder(w).Encode(map[string]any{
				"id": id, "status": "released",
			})
		default:
			_ = json.NewEncoder(w).Encode(map[string]any{
				"id": id, "status": sessions[id],
			})
		}
	})
	return httptest.NewServer(mux)
}

func TestClientCreateSessionDefaults(t *testing.T) {
	srv := fakeServer(t, map[string]string{})
	defer srv.Close()

	c := &Client{apiKey: "k", baseURL: srv.URL}
	s, err := c.CreateSession(CreateSessionOptions{})
	if err != nil {
		t.Fatalf("CreateSession: %v", err)
	}
	if s.ID != "sess_fake1" {
		t.Errorf("got id %q, want sess_fake1", s.ID)
	}
}

func TestWaitReadyTransitions(t *testing.T) {
	srv := fakeServer(t, map[string]string{"sess_x": "ready"})
	defer srv.Close()

	c := &Client{apiKey: "k", baseURL: srv.URL}
	s := &Session{ID: "sess_x", client: c}
	if err := s.WaitReady(WaitReadyOptions{Timeout: 5, PollInterval: 0.1}); err != nil {
		t.Fatalf("WaitReady: %v", err)
	}
	if s.status != "ready" {
		t.Errorf("status = %q, want ready", s.status)
	}
}

func TestWaitReadyTerminalStatusErrors(t *testing.T) {
	srv := fakeServer(t, map[string]string{"sess_err": "error"})
	defer srv.Close()

	c := &Client{apiKey: "k", baseURL: srv.URL}
	s := &Session{ID: "sess_err", client: c}
	err := s.WaitReady(WaitReadyOptions{Timeout: 5, PollInterval: 0.1})
	if err == nil {
		t.Fatal("expected error for terminal status, got nil")
	}
	if !strings.Contains(err.Error(), "error") {
		t.Errorf("error %q should mention the terminal status", err)
	}
}

func TestExecResultSuccess(t *testing.T) {
	srv := fakeServer(t, nil)
	defer srv.Close()

	c := &Client{apiKey: "k", baseURL: srv.URL}
	s := &Session{ID: "sess_e", client: c}
	r, err := s.Device().Exec("ls", ExecOptions{})
	if err != nil {
		t.Fatalf("Exec: %v", err)
	}
	if !r.Success() {
		t.Errorf("Success() = false, want true (ExitCode=%d)", r.ExitCode)
	}
}

type deployCapture struct {
	contentType string
	auth        string
	files       map[string][2]string // field -> {filename, content}
}

func deployServer(t *testing.T, got *deployCapture) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "POST" || r.URL.Path != "/v1/sessions/sess_d/deploy" {
			http.Error(w, "unexpected "+r.Method+" "+r.URL.Path, 404)
			return
		}
		got.contentType = r.Header.Get("Content-Type")
		got.auth = r.Header.Get("Authorization")
		if err := r.ParseMultipartForm(1 << 20); err != nil {
			http.Error(w, err.Error(), 400)
			return
		}
		got.files = map[string][2]string{}
		for field, hs := range r.MultipartForm.File {
			f, _ := hs[0].Open()
			b, _ := io.ReadAll(f)
			f.Close()
			got.files[field] = [2]string{hs[0].Filename, string(b)}
		}
		w.Write([]byte(`{"success":true}`))
	}))
}

func TestDeployMultipartParts(t *testing.T) {
	var got deployCapture
	srv := deployServer(t, &got)
	defer srv.Close()

	c := &Client{apiKey: "k", baseURL: srv.URL}
	s := &Session{ID: "sess_d", client: c}
	err := s.Device().Deploy(DeployOptions{
		Model:  DeployFile{Name: "face.cvimodel", Data: []byte("MODEL")},
		Config: DeployFile{Name: "face.json", Data: "CONFIG"},
		Files: []DeployFile{
			{Name: "build/my_inference", Data: []byte("BIN")},
			{Name: "sample.jpg", Data: []byte("IMG")},
		},
	})
	if err != nil {
		t.Fatalf("Deploy: %v", err)
	}
	if !strings.HasPrefix(got.contentType, "multipart/form-data") {
		t.Errorf("Content-Type = %q, want multipart/form-data", got.contentType)
	}
	if got.auth != "Bearer k" {
		t.Errorf("Authorization = %q, want Bearer k", got.auth)
	}
	want := map[string][2]string{
		"model":  {"face.cvimodel", "MODEL"},
		"config": {"face.json", "CONFIG"},
		"file_0": {"my_inference", "BIN"},
		"file_1": {"sample.jpg", "IMG"},
	}
	if len(got.files) != len(want) {
		t.Errorf("parts = %v, want %v", got.files, want)
	}
	for field, w := range want {
		if got.files[field] != w {
			t.Errorf("part %s = %v, want %v", field, got.files[field], w)
		}
	}
}

func TestDeployWithoutModelErrors(t *testing.T) {
	var got deployCapture
	srv := deployServer(t, &got)
	defer srv.Close()

	c := &Client{apiKey: "k", baseURL: srv.URL}
	s := &Session{ID: "sess_d", client: c}
	err := s.Device().Deploy(DeployOptions{})
	if err == nil || !strings.Contains(err.Error(), "requires model") {
		t.Fatalf("err = %v, want a requires-model error", err)
	}
	if got.files != nil {
		t.Errorf("request was sent without a model: %v", got.files)
	}
}

// TestDeployFromJSArrayBuffer drives the JS-to-Go conversion k6 uses, so an
// ArrayBuffer from open(path, "b") reaches the upload as raw bytes.
func TestDeployFromJSArrayBuffer(t *testing.T) {
	var got deployCapture
	srv := deployServer(t, &got)
	defer srv.Close()

	rt := sobek.New()
	rt.SetFieldNameMapper(common.FieldNameMapper{})
	v, err := rt.RunString(`({
		model: { name: "face.cvimodel", data: new Uint8Array([0, 1, 254, 255]).buffer },
		files: [{ name: "my_inference", data: new Uint8Array([127, 69, 76, 70]).buffer }],
	})`)
	if err != nil {
		t.Fatalf("RunString: %v", err)
	}
	var opts DeployOptions
	if err := rt.ExportTo(v, &opts); err != nil {
		t.Fatalf("ExportTo: %v", err)
	}

	c := &Client{apiKey: "k", baseURL: srv.URL}
	s := &Session{ID: "sess_d", client: c}
	if err := s.Device().Deploy(opts); err != nil {
		t.Fatalf("Deploy: %v", err)
	}
	if got.files["model"] != [2]string{"face.cvimodel", "\x00\x01\xfe\xff"} {
		t.Errorf("model part = %q", got.files["model"])
	}
	if got.files["file_0"] != [2]string{"my_inference", "\x7fELF"} {
		t.Errorf("file_0 part = %q", got.files["file_0"])
	}
	if _, ok := got.files["config"]; ok {
		t.Errorf("unexpected config part")
	}
}

func TestInferenceRunReturnsStats(t *testing.T) {
	srv := fakeServer(t, nil)
	defer srv.Close()

	c := &Client{apiKey: "k", baseURL: srv.URL}
	// module-less Session so we can drive Inference.Run without
	// real k6 VU state; emit() short-circuits on nil state.
	s := &Session{ID: "sess_r", client: c, module: &Module{}}
	stats, err := s.Device().Inference().Run(10)
	if err != nil {
		t.Fatalf("Run: %v", err)
	}
	if stats.FPS.Avg != 17.4 {
		t.Errorf("FPS.Avg = %v, want 17.4", stats.FPS.Avg)
	}
	if stats.DetectionCount != 42 {
		t.Errorf("DetectionCount = %d, want 42", stats.DetectionCount)
	}
}
