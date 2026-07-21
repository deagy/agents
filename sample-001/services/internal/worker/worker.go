package worker

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/cenkalti/backoff/v7"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"

	"example.com/sample-001/services/internal/storage"
)

type Worker struct {
	Pool           *pgxpool.Pool
	Objects        *storage.Filesystem
	Kind           string
	ScannerVersion string
	PolicyVersion  string
	FailureSHA256  string
	MaxAttempts    uint
}

var errCompleted = errors.New("job completed in fenced transaction")

type job struct {
	ID, Token, Version, Size                      int64
	DocumentID, ObjectKey, SHA256, Policy, Status string
}

func (w *Worker) Run(ctx context.Context) error {
	if w.MaxAttempts == 0 {
		w.MaxAttempts = 3
	}
	operation := func() (struct{}, error) {
		err := w.runOnce(ctx)
		if errors.Is(err, pgx.ErrNoRows) {
			return struct{}{}, nil
		}
		return struct{}{}, err
	}
	_, err := backoff.Retry(ctx, operation, backoff.WithBackOff(backoff.NewExponentialBackOff()), backoff.WithMaxTries(w.MaxAttempts))
	return err
}

func (w *Worker) runOnce(ctx context.Context) error {
	job, err := w.claim(ctx)
	if err != nil {
		return err
	}
	var processErr error
	switch w.Kind {
	case "scan":
		processErr = w.scan(ctx, job)
	case "promotion":
		processErr = w.promote(ctx, job)
	case "deletion":
		processErr = w.delete(ctx, job)
	case "reconciliation":
		processErr = w.reconcile(ctx, job)
	default:
		processErr = fmt.Errorf("unsupported worker kind %q", w.Kind)
	}
	if processErr != nil {
		if errors.Is(processErr, errCompleted) {
			return nil
		}
		return w.fail(ctx, job, processErr)
	}
	return w.complete(ctx, job)
}

func (w *Worker) claim(ctx context.Context) (job, error) {
	var claimed job
	ctx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	tx, err := w.Pool.Begin(ctx)
	if err != nil {
		return job{}, err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	err = tx.QueryRow(ctx, `SELECT j.id,j.fencing_token+1,d.id::text,COALESCE(d.object_key::text,''),COALESCE(d.sha256,''),COALESCE(d.byte_size,0),d.object_version,d.policy_version,d.status::text FROM jobs j JOIN documents d ON d.id=j.document_id WHERE j.kind=$1 AND ((j.status='ready' AND j.available_at<=now()) OR (j.status='leased' AND j.leased_until<now())) ORDER BY j.id FOR UPDATE OF j SKIP LOCKED LIMIT 1`, w.Kind).Scan(&claimed.ID, &claimed.Token, &claimed.DocumentID, &claimed.ObjectKey, &claimed.SHA256, &claimed.Size, &claimed.Version, &claimed.Policy, &claimed.Status)
	if err != nil {
		return job{}, err
	}
	_, err = tx.Exec(ctx, `UPDATE jobs SET status='leased',leased_until=now()+interval '30 seconds',fencing_token=$2,attempts=attempts+1,updated_at=now() WHERE id=$1`, claimed.ID, claimed.Token)
	if err != nil {
		return job{}, err
	}
	return claimed, tx.Commit(ctx)
}

func (w *Worker) scan(ctx context.Context, j job) error {
	if w.FailureSHA256 != "" && strings.EqualFold(w.FailureSHA256, j.SHA256) {
		return errors.New("injected scanner failure")
	}
	if j.Policy != w.PolicyVersion {
		return errors.New("policy version mismatch")
	}
	tx, cancel, err := w.fencedTransaction(ctx, j, "pending_scan", "scanning")
	if err != nil {
		return err
	}
	defer cancel()
	defer func() { _ = tx.Rollback(context.Background()) }()
	rejected, err := w.Objects.ScanQuarantine(j.ObjectKey, j.SHA256, j.Size)
	if err != nil {
		return err
	}
	verdict := "clean"
	if rejected {
		verdict = "rejected"
	}
	_, err = tx.Exec(ctx, `INSERT INTO scan_results(document_id,object_version,policy_version,sha256,byte_size,verdict,scanner_version) VALUES($1,$2,$3,$4,$5,$6,$7)`, j.DocumentID, j.Version, j.Policy, j.SHA256, j.Size, verdict, w.ScannerVersion)
	if err != nil {
		return err
	}
	if rejected {
		var command pgconn.CommandTag
		command, err = tx.Exec(ctx, `UPDATE documents SET status='rejected',status_message='malware_detected',updated_at=now() WHERE id=$1 AND object_version=$2 AND sha256=$3 AND byte_size=$4 AND policy_version=$5 AND status IN ('pending_scan','scanning')`, j.DocumentID, j.Version, j.SHA256, j.Size, j.Policy)
		if err == nil && command.RowsAffected() != 1 {
			err = errors.New("stale document version")
		}
	} else {
		var command pgconn.CommandTag
		command, err = tx.Exec(ctx, `UPDATE documents SET status='scanning',updated_at=now() WHERE id=$1 AND object_version=$2 AND sha256=$3 AND byte_size=$4 AND policy_version=$5 AND status='pending_scan'`, j.DocumentID, j.Version, j.SHA256, j.Size, j.Policy)
		if err == nil && command.RowsAffected() != 1 {
			err = errors.New("stale document version")
		}
		if err == nil {
			_, err = tx.Exec(ctx, `INSERT INTO jobs(kind,document_id) VALUES('promotion',$1)`, j.DocumentID)
		}
	}
	if err != nil {
		return err
	}
	if err = w.completeFenced(ctx, tx, j); err != nil {
		return err
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	return errCompleted
}
func (w *Worker) promote(ctx context.Context, j job) error {
	if j.Policy != w.PolicyVersion {
		return errors.New("policy version mismatch")
	}
	tx, cancel, err := w.fencedTransaction(ctx, j, "pending_scan", "scanning")
	if err != nil {
		return err
	}
	defer cancel()
	defer func() { _ = tx.Rollback(context.Background()) }()
	if err := w.Objects.Promote(j.ObjectKey, j.SHA256, j.Size); err != nil {
		return err
	}
	command, err := tx.Exec(ctx, `UPDATE documents SET status='clean',updated_at=now() WHERE id=$1 AND object_version=$2 AND sha256=$3 AND byte_size=$4 AND policy_version=$5 AND status IN ('pending_scan','scanning')`, j.DocumentID, j.Version, j.SHA256, j.Size, j.Policy)
	if err != nil {
		return err
	}
	if command.RowsAffected() != 1 {
		return errors.New("stale document version")
	}
	if err = w.completeFenced(ctx, tx, j); err != nil {
		return err
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	return errCompleted
}
func (w *Worker) delete(ctx context.Context, j job) error {
	tx, cancel, err := w.fencedTransaction(ctx, j, "deleting")
	if err != nil {
		return err
	}
	defer cancel()
	defer func() { _ = tx.Rollback(context.Background()) }()
	if j.ObjectKey != "" {
		if err := w.Objects.Delete(j.ObjectKey); err != nil {
			return err
		}
	}
	command, err := tx.Exec(ctx, `UPDATE documents SET status='deleted',updated_at=now() WHERE id=$1 AND object_version=$2 AND status='deleting'`, j.DocumentID, j.Version)
	if err != nil {
		return err
	}
	if command.RowsAffected() != 1 {
		return errors.New("stale deletion")
	}
	if err = w.completeFenced(ctx, tx, j); err != nil {
		return err
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	return errCompleted
}
func (w *Worker) reconcile(ctx context.Context, j job) error {
	tx, cancel, err := w.fencedTransaction(ctx, j, "clean", "pending_scan", "scanning", "rejected", "failed", "deleting", "deleted")
	if err != nil {
		return err
	}
	defer cancel()
	defer func() { _ = tx.Rollback(context.Background()) }()
	switch j.Status {
	case "clean":
		file, err := w.Objects.OpenClean(j.ObjectKey, j.SHA256, j.Size)
		if err != nil {
			return err
		}
		if err = file.Close(); err != nil {
			return err
		}
	case "pending_scan", "scanning":
		if _, err = w.Objects.ScanQuarantine(j.ObjectKey, j.SHA256, j.Size); err != nil {
			return err
		}
	case "rejected", "failed", "deleting", "deleted":
		if err = w.Objects.Delete(j.ObjectKey); err != nil {
			return err
		}
	default:
		return errors.New("document state is not reconcilable")
	}
	if err = w.completeFenced(ctx, tx, j); err != nil {
		return err
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	return errCompleted
}
func (w *Worker) fencedTransaction(parent context.Context, j job, allowed ...string) (pgx.Tx, context.CancelFunc, error) {
	ctx, cancel := context.WithTimeout(parent, 45*time.Second)
	tx, err := w.Pool.Begin(ctx)
	if err != nil {
		cancel()
		return nil, func() {}, err
	}
	var status string
	err = tx.QueryRow(ctx, `SELECT d.status::text FROM jobs q JOIN documents d ON d.id=q.document_id WHERE q.id=$1 AND q.status='leased' AND q.fencing_token=$2 AND q.leased_until>now() AND d.id=$3 AND d.object_version=$4 AND COALESCE(d.sha256,'')=$5 AND COALESCE(d.byte_size,0)=$6 AND d.policy_version=$7 FOR UPDATE OF q,d`, j.ID, j.Token, j.DocumentID, j.Version, j.SHA256, j.Size, j.Policy).Scan(&status)
	if err != nil {
		_ = tx.Rollback(ctx)
		cancel()
		return nil, func() {}, errors.New("stale job lease")
	}
	for _, candidate := range allowed {
		if status == candidate {
			return tx, cancel, nil
		}
	}
	_ = tx.Rollback(ctx)
	cancel()
	return nil, func() {}, errors.New("stale document state")
}
func (w *Worker) completeFenced(ctx context.Context, tx pgx.Tx, j job) error {
	command, err := tx.Exec(ctx, `UPDATE jobs SET status='complete',leased_until=NULL,updated_at=now() WHERE id=$1 AND fencing_token=$2 AND status='leased'`, j.ID, j.Token)
	if err != nil {
		return err
	}
	if command.RowsAffected() != 1 {
		return errors.New("stale job lease")
	}
	return nil
}
func (w *Worker) complete(ctx context.Context, j job) error {
	ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	command, err := w.Pool.Exec(ctx, `UPDATE jobs SET status='complete',leased_until=NULL,updated_at=now() WHERE id=$1 AND fencing_token=$2 AND status='leased'`, j.ID, j.Token)
	if err != nil {
		return err
	}
	if command.RowsAffected() != 1 {
		return errors.New("stale job lease")
	}
	return nil
}
func (w *Worker) fail(ctx context.Context, j job, cause error) error {
	ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	code := "worker_failure"
	command, err := w.Pool.Exec(ctx, `UPDATE jobs SET status=CASE WHEN attempts>=5 THEN 'dead'::job_status ELSE 'ready'::job_status END,available_at=now()+interval '5 seconds',leased_until=NULL,last_error_code=$3,updated_at=now() WHERE id=$1 AND fencing_token=$2 AND status='leased'`, j.ID, j.Token, code)
	if err != nil {
		return errors.Join(cause, err)
	}
	if command.RowsAffected() != 1 {
		return errors.Join(cause, errors.New("stale job lease"))
	}
	return cause
}
