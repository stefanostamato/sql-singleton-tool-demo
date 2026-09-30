import { REPO_URL, WRITEUP_URL } from "../config";

export default function Footer() {
  return (
    <footer className="footer">
      <div className="wrap">
        <p>
          <a href={REPO_URL}>Code</a> <span aria-hidden="true">·</span>{" "}
          <a href={WRITEUP_URL}>Writeup</a> <span aria-hidden="true">·</span>{" "}
          <span className="byline">
            <a href="https://zarins.tech" target="_blank" rel="noopener">
              by Stefano Zarins Stamato
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M7 7h10v10" />
                <path d="M7 17 17 7" />
              </svg>
            </a>
          </span>
        </p>
        <p className="muted">Harbor &amp; Vale LLP and all data here are fictional.</p>
      </div>
    </footer>
  );
}
