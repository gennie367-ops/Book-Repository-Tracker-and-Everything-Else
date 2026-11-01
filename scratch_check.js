
    let allBooks = [];
    let currentView = "all"; // 'all', 'ebooks', 'audiobooks', 'tbr', 'read', 'authors', 'series', 'reviews'
    let activeSubFilter = null;
    let searchTimer = null;
    let attachTargetBookId = null;

    // Filter & Sort State
    let currentSort = "newest"; // 'newest', 'oldest', 'title_asc', 'title_desc', 'author_asc', 'author_desc', 'rating_desc', 'year_desc', 'year_asc'
    let filterFormat = "all"; // 'all', 'ebook', 'audiobook'
    let filterStatus = "all"; // 'all', 'unread', 'read', 'tbr'
    let filterRating = "all"; // 'all', '5', '4+', '3+', 'reviewed', 'unrated'
    let inViewFilterText = "";
    let lastRenderedToolbarKey = null;

    const VIEW_INFO = {
      all: { title: "📚 All Books", subtitle: "All ebooks and audiobooks you own and have uploaded to your server" },
      ebooks: { title: "📖 Ebooks Library", subtitle: "Ebooks you own — read online, download, or send wirelessly to your Kindle" },
      audiobooks: { title: "🎧 Audiobooks Library", subtitle: "Audiobooks you own — stream in your browser or download to any device" },
      tbr: { title: "🔖 To Be Read / Listen (TBR)", subtitle: "Your reading & listening wishlist — stays separate until uploaded" },
      read: { title: "✅ Read / Finished", subtitle: "Books and audiobooks you have finished" },
      authors: { title: "✍️ Authors", subtitle: "Browse your owned library grouped by author" },
      series: { title: "📖 Book Series", subtitle: "Browse your owned library organized in series order" },
      reviews: { title: "💬 Reviews", subtitle: "Your personal book reviews, ratings, favorite quotes, and characters" }
    };

    function showToast(msg) {
      const t = document.getElementById("toast");
      t.textContent = msg;
      t.style.display = "block";
      clearTimeout(t._timer);
      t._timer = setTimeout(() => { t.style.display = "none"; }, 3600);
    }

    function escapeHtml(str) {
      return String(str || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }

    function getTitleSortKey(title) {
      const t = (title || "").trim().toLowerCase();
      return t.replace(/^(the|a|an)\s+/i, "");
    }

    function getAuthorSortKey(author) {
      const a = (author || "").trim();
      if (!a) return "zzzz";
      const parts = a.split(/\s+/);
      if (parts.length >= 2 && !a.includes(",")) {
        return (parts[parts.length - 1] + ", " + parts.slice(0, -1).join(" ")).toLowerCase();
      }
      return a.toLowerCase();
    }

    function sortBooksList(list, sortKey) {
      const sorted = [...list];
      if (sortKey === "title_asc") {
        sorted.sort((a, b) => getTitleSortKey(a.title).localeCompare(getTitleSortKey(b.title), undefined, { sensitivity: "base" }));
      } else if (sortKey === "title_desc") {
        sorted.sort((a, b) => getTitleSortKey(b.title).localeCompare(getTitleSortKey(a.title), undefined, { sensitivity: "base" }));
      } else if (sortKey === "author_asc") {
        sorted.sort((a, b) => getAuthorSortKey(a.author).localeCompare(getAuthorSortKey(b.author), undefined, { sensitivity: "base" }));
      } else if (sortKey === "author_desc") {
        sorted.sort((a, b) => getAuthorSortKey(b.author).localeCompare(getAuthorSortKey(a.author), undefined, { sensitivity: "base" }));
      } else if (sortKey === "rating_desc") {
        sorted.sort((a, b) => (b.rating || 0) - (a.rating || 0) || (b.id || 0) - (a.id || 0));
      } else if (sortKey === "year_desc") {
        sorted.sort((a, b) => (parseInt(b.published_year) || 0) - (parseInt(a.published_year) || 0) || (b.id || 0) - (a.id || 0));
      } else if (sortKey === "year_asc") {
        sorted.sort((a, b) => (parseInt(a.published_year) || 9999) - (parseInt(b.published_year) || 9999) || (a.id || 0) - (b.id || 0));
      } else if (sortKey === "oldest") {
        sorted.sort((a, b) => (a.id || 0) - (b.id || 0));
      } else {
        // newest (default)
        sorted.sort((a, b) => (b.id || 0) - (a.id || 0));
      }
      return sorted;
    }

    function setSort(val) {
      currentSort = val;
      renderCurrentView();
    }

    function setFilterFormat(val) {
      filterFormat = val;
      renderCurrentView();
    }

    function setFilterStatus(val) {
      filterStatus = val;
      renderCurrentView();
    }

    function setFilterRating(val) {
      filterRating = val;
      renderCurrentView();
    }

    let inViewFilterTimer = null;
    function handleInViewFilter(val) {
      inViewFilterText = val;
      clearTimeout(inViewFilterTimer);
      inViewFilterTimer = setTimeout(() => {
        renderCurrentView();
      }, 80);
    }

    function resetFilters() {
      currentSort = "newest";
      filterFormat = (currentView === "ebooks" ? "ebook" : (currentView === "audiobooks" ? "audiobook" : "all"));
      filterStatus = (currentView === "read" ? "read" : "all");
      filterRating = "all";
      inViewFilterText = "";
      renderCurrentView();
    }

    function renderToolbar() {
      const tb = document.getElementById("filterSortToolbar");
      if (!tb) return;

      const isAuthorDrill = (currentView === "authors" && activeSubFilter);
      const showToolbar = ["all", "ebooks", "audiobooks", "tbr", "read"].includes(currentView) || isAuthorDrill;

      if (!showToolbar) {
        tb.style.display = "none";
        lastRenderedToolbarKey = null;
        return;
      }

      tb.style.display = "flex";

      const showFormatFilter = ["all", "tbr", "read"].includes(currentView) || isAuthorDrill;
      const showStatusFilter = ["all", "ebooks", "audiobooks"].includes(currentView);

      const viewKey = `${currentView}_${isAuthorDrill}_${showFormatFilter}_${showStatusFilter}`;
      if (lastRenderedToolbarKey !== viewKey) {
        lastRenderedToolbarKey = viewKey;
        tb.innerHTML = `
          <div class="filter-sort-group">
            <div class="toolbar-search">
              <span class="search-icon">🔍</span>
              <input
                type="text"
                id="inViewSearchInput"
                placeholder="Filter current shelf..."
                autocomplete="off"
                oninput="handleInViewFilter(this.value)"
              />
            </div>

            ${showFormatFilter ? `
              <select class="toolbar-select" id="filterFormatSelect" onchange="setFilterFormat(this.value)" title="Filter by Format">
                <option value="all">Format: All</option>
                <option value="ebook">📖 Ebooks Only</option>
                <option value="audiobook">🎧 Audiobooks Only</option>
              </select>
            ` : ''}

            ${showStatusFilter ? `
              <select class="toolbar-select" id="filterStatusSelect" onchange="setFilterStatus(this.value)" title="Filter by Reading Status">
                <option value="all">Status: All</option>
                <option value="unread">○ Unread Only</option>
                <option value="read">✅ Read Only</option>
                <option value="tbr">🔖 On TBR</option>
              </select>
            ` : ''}

            <select class="toolbar-select" id="filterRatingSelect" onchange="setFilterRating(this.value)" title="Filter by Star Rating">
              <option value="all">Rating: All</option>
              <option value="5">★★★★★ (5 Stars)</option>
              <option value="4+">★★★★☆ (4+ Stars)</option>
              <option value="3+">★★★☆☆ (3+ Stars)</option>
              <option value="reviewed">💬 Has Review</option>
              <option value="unrated">○ Unrated</option>
            </select>
          </div>

          <div class="filter-sort-group">
            <div style="display:flex; align-items:center; gap:0.35rem;">
              <span class="toolbar-label">Sort:</span>
              <select class="toolbar-select" id="sortSelect" onchange="setSort(this.value)" title="Sort Catalog">
                <option value="newest">🕒 Recently Added</option>
                <option value="oldest">⏳ Oldest Added</option>
                <option value="title_asc">🔤 Title (A → Z)</option>
                <option value="title_desc">🔤 Title (Z → A)</option>
                <option value="author_asc">✍️ Author (A → Z)</option>
                <option value="author_desc">✍️ Author (Z → A)</option>
                <option value="rating_desc">⭐ Highest Rating</option>
                <option value="year_desc">📅 Year (Newest)</option>
                <option value="year_asc">📅 Year (Oldest)</option>
              </select>
            </div>

            <button class="toolbar-reset-btn" id="toolbarResetBtn" onclick="resetFilters()" style="display:none;" title="Reset filters">
              ✕ Reset
            </button>

            <span class="toolbar-count-badge" id="toolbarCountBadge">0 items</span>
          </div>
        `;
      }

      const searchEl = document.getElementById("inViewSearchInput");
      if (searchEl && searchEl.value !== inViewFilterText && document.activeElement !== searchEl) {
        searchEl.value = inViewFilterText;
      }
      const fmtEl = document.getElementById("filterFormatSelect");
      if (fmtEl) fmtEl.value = filterFormat;
      const stEl = document.getElementById("filterStatusSelect");
      if (stEl) stEl.value = filterStatus;
      const rtEl = document.getElementById("filterRatingSelect");
      if (rtEl) rtEl.value = filterRating;
      const sEl = document.getElementById("sortSelect");
      if (sEl) sEl.value = currentSort;

      const defaultFormat = (currentView === "ebooks" ? "ebook" : (currentView === "audiobooks" ? "audiobook" : "all"));
      const defaultStatus = (currentView === "read" ? "read" : "all");
      const isFiltered = (
        currentSort !== "newest" ||
        (filterFormat !== defaultFormat && showFormatFilter) ||
        (filterStatus !== defaultStatus && showStatusFilter) ||
        filterRating !== "all" ||
        inViewFilterText.trim().length > 0
      );
      const rBtn = document.getElementById("toolbarResetBtn");
      if (rBtn) rBtn.style.display = isFiltered ? "inline-flex" : "none";
    }

    function switchView(viewName, subFilter = null) {
      currentView = viewName;
      activeSubFilter = subFilter;
      inViewFilterText = "";

      // Default format filter per view
      if (viewName === "ebooks") {
        filterFormat = "ebook";
      } else if (viewName === "audiobooks") {
        filterFormat = "audiobook";
      } else if (viewName === "all") {
        filterFormat = "all";
      }

      // Default status filter per view
      if (viewName === "read") {
        filterStatus = "read";
      } else if (viewName === "all" || viewName === "ebooks" || viewName === "audiobooks") {
        filterStatus = "all";
      }

      document.querySelectorAll(".nav-item").forEach(el => el.classList.remove("active"));
      const navBtn = document.getElementById(`nav-${viewName}`);
      if (navBtn) navBtn.classList.add("active");

      const info = VIEW_INFO[viewName] || VIEW_INFO.all;
      document.getElementById("viewTitle").textContent = subFilter ? `${info.title}: ${subFilter}` : info.title;
      document.getElementById("viewSubtitle").textContent = info.subtitle;
      renderCurrentView();
    }

    async function loadBooks(query = "") {
      const url = query.trim()
        ? `/books/search?q=${encodeURIComponent(query.trim())}`
        : `/books`;
      try {
        const res = await fetch(url);
        const data = await res.json();
        allBooks = data.books || data.matches || [];
        updateSidebarCounts();
        renderCurrentView();
      } catch (err) {
        console.error(err);
      }
    }

    function updateSidebarCounts() {
      const ownedEbooks = allBooks.filter(b => b.has_file && b.media_type !== "audiobook");
      const ownedAudiobooks = allBooks.filter(b => b.has_file && b.media_type === "audiobook");
      const allOwned = allBooks.filter(b => b.has_file);

      document.getElementById("count-all").textContent = allOwned.length;
      if (document.getElementById("count-ebooks")) {
        document.getElementById("count-ebooks").textContent = ownedEbooks.length;
      }
      document.getElementById("count-audiobooks").textContent = ownedAudiobooks.length;
      document.getElementById("count-tbr").textContent = allBooks.filter(b => b.reading_status === "tbr" && !b.is_read).length;
      document.getElementById("count-read").textContent = allBooks.filter(b => b.is_read || b.reading_status === "read").length;

      const authorsSet = new Set(allOwned.map(b => (b.author || "Unknown Author").trim()).filter(Boolean));
      document.getElementById("count-authors").textContent = authorsSet.size;

      const seriesSet = new Set(allOwned.map(b => (b.series_name || "").trim()).filter(Boolean));
      document.getElementById("count-series").textContent = seriesSet.size;

      const reviewedCount = allBooks.filter(b =>
        (b.rating && b.rating > 0) ||
        (b.review && b.review.trim()) ||
        (b.review_headline && b.review_headline.trim()) ||
        (b.favorite_quotes && b.favorite_quotes.trim()) ||
        (b.favorite_characters && b.favorite_characters.trim())
      ).length;
      document.getElementById("count-reviews").textContent = reviewedCount;
    }

    function handleSearch(val) {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => loadBooks(val), 200);
    }

    function renderCurrentView() {
      const subBar = document.getElementById("subFilterBar");
      subBar.style.display = "none";
      subBar.innerHTML = "";

      renderToolbar();

      if (currentView === "authors" && !activeSubFilter) {
        renderAuthorsView();
        return;
      }
      if (currentView === "series") {
        renderSeriesView();
        return;
      }
      if (currentView === "reviews") {
        renderReviewsView();
        return;
      }

      let filtered = [...allBooks];
      let totalViewCount = 0;

      // 1. BASE VIEW FILTER
      if (currentView === "all") {
        filtered = filtered.filter(b => b.has_file);
      } else if (currentView === "ebooks") {
        filtered = filtered.filter(b => b.has_file && b.media_type !== "audiobook");
      } else if (currentView === "audiobooks") {
        filtered = filtered.filter(b => b.has_file && b.media_type === "audiobook");
      } else if (currentView === "tbr") {
        const allTbr = filtered.filter(b => b.reading_status === "tbr" && !b.is_read);
        const ownedTbrCount = allTbr.filter(b => b.has_file).length;
        const wishlistTbrCount = allTbr.filter(b => !b.has_file).length;

        subBar.style.display = "flex";
        subBar.innerHTML = `
          <button class="btn ${!activeSubFilter ? 'btn-primary' : 'btn-secondary'} btn-sm" onclick="switchView('tbr', null)">
            All TBR (${allTbr.length})
          </button>
          <button class="btn ${activeSubFilter === 'wishlist' ? 'btn-primary' : 'btn-secondary'} btn-sm" onclick="switchView('tbr', 'wishlist')">
            Wishlist / Need File (${wishlistTbrCount})
          </button>
          <button class="btn ${activeSubFilter === 'owned' ? 'btn-primary' : 'btn-secondary'} btn-sm" onclick="switchView('tbr', 'owned')">
            Owned & Ready (${ownedTbrCount})
          </button>
        `;

        if (activeSubFilter === "wishlist") {
          filtered = allTbr.filter(b => !b.has_file);
        } else if (activeSubFilter === "owned") {
          filtered = allTbr.filter(b => b.has_file);
        } else {
          filtered = allTbr;
        }
      } else if (currentView === "read") {
        filtered = filtered.filter(b => b.is_read || b.reading_status === "read");
      } else if (currentView === "authors" && activeSubFilter) {
        subBar.style.display = "flex";
        subBar.innerHTML = `
          <button class="btn btn-secondary btn-sm" onclick="switchView('authors', null)">← Back to All Authors</button>
          <span class="badge">Author: ${escapeHtml(activeSubFilter)}</span>
        `;
        filtered = filtered.filter(b => b.has_file && (b.author || "Unknown Author").trim() === activeSubFilter);
      }

      totalViewCount = filtered.length;

      // 2. FORMAT FILTER (Ebook vs Audiobook)
      if (filterFormat === "ebook") {
        filtered = filtered.filter(b => b.media_type !== "audiobook");
      } else if (filterFormat === "audiobook") {
        filtered = filtered.filter(b => b.media_type === "audiobook");
      }

      // 3. READING STATUS FILTER
      if (filterStatus === "unread") {
        filtered = filtered.filter(b => !b.is_read && b.reading_status !== "read" && b.reading_status !== "tbr");
      } else if (filterStatus === "read") {
        filtered = filtered.filter(b => b.is_read || b.reading_status === "read");
      } else if (filterStatus === "tbr") {
        filtered = filtered.filter(b => b.reading_status === "tbr" && !b.is_read);
      }

      // 4. RATING FILTER
      if (filterRating === "5") {
        filtered = filtered.filter(b => b.rating === 5);
      } else if (filterRating === "4+") {
        filtered = filtered.filter(b => b.rating >= 4);
      } else if (filterRating === "3+") {
        filtered = filtered.filter(b => b.rating >= 3);
      } else if (filterRating === "reviewed") {
        filtered = filtered.filter(b => (b.rating > 0) || (b.review && b.review.trim()));
      } else if (filterRating === "unrated") {
        filtered = filtered.filter(b => (!b.rating || b.rating === 0) && (!b.review || !b.review.trim()));
      }

      // 5. IN-VIEW TEXT FILTER
      if (inViewFilterText.trim()) {
        const q = inViewFilterText.trim().toLowerCase();
        filtered = filtered.filter(b =>
          (b.title && b.title.toLowerCase().includes(q)) ||
          (b.author && b.author.toLowerCase().includes(q)) ||
          (b.series_name && b.series_name.toLowerCase().includes(q)) ||
          (b.narrator && b.narrator.toLowerCase().includes(q))
        );
      }

      // 6. SORTING
      filtered = sortBooksList(filtered, currentSort);

      // Update toolbar count badge
      const countEl = document.getElementById("toolbarCountBadge");
      if (countEl) {
        if (filtered.length !== totalViewCount) {
          countEl.textContent = `${filtered.length} of ${totalViewCount} item${totalViewCount === 1 ? '' : 's'}`;
        } else {
          countEl.textContent = `${filtered.length} item${filtered.length === 1 ? '' : 's'}`;
        }
      }

      renderBookCardsGrid(filtered);
    }

    // --- AUTHORS VIEW ---
    function renderAuthorsView() {
      const container = document.getElementById("bookContainer");
      const subBar = document.getElementById("subFilterBar");

      const authorGroups = {};
      for (const b of allBooks.filter(x => x.has_file)) {
        const auth = (b.author || "Unknown Author").trim();
        if (!authorGroups[auth]) authorGroups[auth] = [];
        authorGroups[auth].push(b);
      }

      const sortedAuthors = Object.keys(authorGroups).sort((a, b) => a.localeCompare(b));
      if (!sortedAuthors.length) {
        renderBookCardsGrid([]);
        return;
      }

      if (activeSubFilter) {
        subBar.style.display = "flex";
        subBar.innerHTML = `
          <button class="btn btn-secondary btn-sm" onclick="switchView('authors', null)">← Back to All Authors</button>
          <span class="badge">Showing ${authorGroups[activeSubFilter]?.length || 0} item(s) by ${escapeHtml(activeSubFilter)}</span>
        `;
        renderBookCardsGrid(authorGroups[activeSubFilter] || []);
        return;
      }

      container.innerHTML = `
        <div class="group-grid">
          ${sortedAuthors.map(author => {
            const list = authorGroups[author];
            const readCount = list.filter(b => b.is_read || b.reading_status === "read").length;
            return `
              <div class="group-card" onclick="switchView('authors', '${escapeHtml(author).replace(/'/g, "\\'")}')">
                <h3>✍️ ${escapeHtml(author)}</h3>
                <div class="group-card-meta">
                  <span>${list.length} item${list.length === 1 ? "" : "s"}</span>
                  <span>✅ ${readCount} finished</span>
                </div>
              </div>
            `;
          }).join("")}
        </div>
      `;
    }

    // --- SERIES VIEW ---
    function renderSeriesView() {
      const container = document.getElementById("bookContainer");
      const seriesMap = {};

      for (const b of allBooks.filter(x => x.has_file)) {
        const s = (b.series_name || "").trim();
        if (s) {
          if (!seriesMap[s]) seriesMap[s] = [];
          seriesMap[s].push(b);
        }
      }

      const seriesNames = Object.keys(seriesMap).sort((a, b) => a.localeCompare(b));
      if (!seriesNames.length) {
        container.innerHTML = `
          <div class="empty-state">
            <h2>No book series tagged yet</h2>
            <p>Series names and book numbers (like "The Empyrean #1") are detected automatically from Goodreads and Audible, or you can add a Series Name in "✏️ Edit / Review".</p>
          </div>
        `;
        return;
      }

      container.innerHTML = seriesNames.map(sName => {
        const books = seriesMap[sName].sort((a, b) => {
          const na = parseFloat(a.series_number) || 999;
          const nb = parseFloat(b.series_number) || 999;
          return na - nb;
        });
        const readCount = books.filter(b => b.is_read || b.reading_status === "read").length;
        return `
          <div class="series-section">
            <div class="series-header">
              <h3>📖 ${escapeHtml(sName)} <span class="badge">${books.length} item(s) • ${readCount} finished</span></h3>
            </div>
            <div class="book-grid">
              ${books.map(b => renderSingleBookCard(b)).join("")}
            </div>
          </div>
        `;
      }).join("");
    }

    // --- REVIEWS VIEW ---
    function renderReviewsView() {
      const container = document.getElementById("bookContainer");
      const subBar = document.getElementById("subFilterBar");
      subBar.style.display = "flex";

      const reviewedBooks = allBooks.filter(b =>
        (b.rating && b.rating > 0) ||
        (b.review && b.review.trim()) ||
        (b.review_headline && b.review_headline.trim()) ||
        (b.favorite_quotes && b.favorite_quotes.trim()) ||
        (b.favorite_characters && b.favorite_characters.trim())
      );
      const avg = reviewedBooks.filter(b => b.rating > 0).reduce((acc, b, _, arr) => acc + b.rating / arr.length, 0);

      subBar.innerHTML = `
        <button class="btn ${!activeSubFilter ? 'btn-primary' : 'btn-secondary'} btn-sm" onclick="switchView('reviews', null)">
          All Reviews (${reviewedBooks.length})
        </button>
        ${[5, 4, 3, 2, 1].map(star => {
          const count = reviewedBooks.filter(b => b.rating === star).length;
          return `
            <button class="btn ${activeSubFilter === star ? 'btn-primary' : 'btn-secondary'} btn-sm" onclick="switchView('reviews', ${star})">
              ${"★".repeat(star)} (${count})
            </button>
          `;
        }).join("")}
        ${avg > 0 ? `<span class="badge" style="margin-left:auto;">Average: ${avg.toFixed(1)} ★</span>` : ""}
      `;

      const list = activeSubFilter
        ? reviewedBooks.filter(b => b.rating === activeSubFilter)
        : reviewedBooks;

      const searchBarHtml = `
        <div class="review-search-bar-wrap">
          <div class="review-search-box">
            <span class="search-icon">🔍</span>
            <input
              type="text"
              id="reviewSearchInput"
              placeholder="Search a book in your library to write or edit a review..."
              oninput="handleReviewBookSearch(this.value)"
              onfocus="handleReviewBookSearch(this.value)"
              autocomplete="off"
            />
            <div id="reviewSearchResults" class="review-search-dropdown" style="display:none;"></div>
          </div>
          <button class="btn btn-primary" onclick="openReviewPickerModal()">
            ✍️ Pick a Book to Review
          </button>
        </div>
      `;

      if (!list.length) {
        container.innerHTML = `
          ${searchBarHtml}
          <div class="empty-state">
            <h2>${activeSubFilter ? `No ${activeSubFilter}-star reviews yet` : "No book reviews written yet"}</h2>
            <p>Use the search bar above or click <strong>Pick a Book to Review</strong> to write a review for any book in your collection — share your star rating, spice level, pace, memorable quotes, favorite characters, and overall thoughts!</p>
            <div style="display:flex; justify-content:center; gap:0.6rem; margin-top:1rem;">
              <button class="btn btn-primary" onclick="openReviewPickerModal()">✍️ Review a Book</button>
            </div>
          </div>
        `;
        return;
      }

      const sortedReviews = sortBooksList(list, currentSort);
      container.innerHTML = `
        ${searchBarHtml}
        <div style="display:flex; flex-direction:column; gap:1.15rem;">
          ${sortedReviews.map(b => renderSingleReviewCard(b)).join("")}
        </div>
      `;
    }

    function renderSingleReviewCard(book) {
      const isAudio = book.media_type === "audiobook";
      const stars = "★".repeat(book.rating || 0) + "☆".repeat(Math.max(0, 5 - (book.rating || 0)));
      const paceMap = {
        "Fast": "⚡ Fast-Paced",
        "Steady": "📖 Steady Pace",
        "Slow": "⏳ Slow Burn"
      };
      const paceLabel = paceMap[book.pace] || (book.pace ? `⏱️ ${book.pace}` : "");

      const coverHtml = book.cover_url
        ? `<img src="${escapeHtml(book.cover_url)}" alt="${escapeHtml(book.title)}" onerror="this.parentElement.innerHTML='<div class=\\'cover-fallback\\'>${escapeHtml(book.title)}</div>'" />`
        : `<div class="cover-fallback">${escapeHtml(book.title)}</div>`;

      return `
        <div class="review-card">
          <div class="review-card-top">
            <div class="cover-wrap ${isAudio ? 'audiobook-cover' : ''}" style="cursor:pointer;" onclick="openReviewModal(${book.id})" title="Click to edit review">
              ${coverHtml}
            </div>
            <div class="review-card-info">
              <div class="badges-row" style="margin-bottom:0.35rem;">
                <span class="badge ${isAudio ? 'badge-audio' : 'badge-muted'}">${isAudio ? '🎧 Audiobook' : '📚 Ebook'}</span>
                ${book.series_name ? `<span class="badge badge-series">📖 ${escapeHtml(book.series_name)}${book.series_number ? ` #${escapeHtml(book.series_number)}` : ''}</span>` : ''}
                ${paceLabel ? `<span class="badge" style="background:rgba(99,102,241,0.18); color:#c7d2fe;">${paceLabel}</span>` : ''}
                ${book.spice_rating > 0 ? `<span class="spice-meter">🌶️ ${'🌶️'.repeat(book.spice_rating)} (${book.spice_rating}/5)</span>` : ''}
              </div>

              <div class="book-title" style="font-size:1.15rem; cursor:pointer;" onclick="openReviewModal(${book.id})">${escapeHtml(book.title)}</div>
              <div class="book-author" style="margin-bottom:0.4rem;">by ${escapeHtml(book.author)}</div>

              <div style="display:flex; align-items:center; gap:0.5rem; margin-bottom:0.6rem;">
                <span style="font-size:1.25rem; color:#f59e0b; letter-spacing:2px;">${stars}</span>
                <span style="font-size:0.85rem; font-weight:700; color:#fcd34d;">${book.rating ? `${book.rating}.0 / 5.0` : 'Unrated'}</span>
              </div>

              ${book.review_headline ? `<div class="review-headline">“${escapeHtml(book.review_headline)}”</div>` : ''}
              ${book.review ? `<div class="review-body-text">${escapeHtml(book.review)}</div>` : ''}

              ${book.favorite_quotes ? `
                <div class="review-quote-box">
                  <div class="review-quote-label">💬 Favorite Quote(s)</div>
                  <div style="font-style:italic; white-space:pre-wrap;">“${escapeHtml(book.favorite_quotes)}”</div>
                </div>
              ` : ''}

              ${book.favorite_characters ? `
                <div class="review-chars-box">
                  <span>👥</span>
                  <strong>Favorite Characters:</strong>
                  <span>${escapeHtml(book.favorite_characters)}</span>
                </div>
              ` : ''}

              ${book.tropes ? `
                <div style="display:flex; flex-wrap:wrap; gap:0.35rem; margin-top:0.45rem;">
                  ${book.tropes.split(',').filter(Boolean).map(t => `<span class="trope-pill">🏷️ ${escapeHtml(t.trim())}</span>`).join('')}
                </div>
              ` : ''}

              <div style="display:flex; gap:0.5rem; margin-top:0.9rem;">
                <button class="btn btn-primary btn-sm" onclick="openReviewModal(${book.id})">✏️ Edit Review</button>
                <button class="btn btn-secondary btn-sm" onclick="clearReview(${book.id}, '${escapeHtml(book.title).replace(/'/g, "\\'")}')">🗑️ Clear Review</button>
              </div>
            </div>
          </div>
        </div>
      `;
    }

    function renderBookCardsGrid(books) {
      const container = document.getElementById("bookContainer");
      if (!books.length) {
        const defaultFormat = (currentView === "ebooks" ? "ebook" : (currentView === "audiobooks" ? "audiobook" : "all"));
        const defaultStatus = (currentView === "read" ? "read" : "all");
        const hasActiveFilters = (
          (filterFormat !== defaultFormat && ["all", "tbr", "read"].includes(currentView)) ||
          (filterStatus !== defaultStatus && ["all", "ebooks", "audiobooks"].includes(currentView)) ||
          filterRating !== "all" ||
          inViewFilterText.trim().length > 0
        );

        if (hasActiveFilters) {
          container.innerHTML = `
            <div class="empty-state">
              <h2>🔍 No books match your current filters</h2>
              <p>Try clearing your search keyword, format, status, or star rating filter to see more items.</p>
              <div style="display:flex; justify-content:center; gap:0.65rem;">
                <button class="btn btn-secondary" onclick="resetFilters()">🔄 Reset Filters</button>
              </div>
            </div>
          `;
          return;
        }

        const isAudio = currentView === "audiobooks" || (currentView === "all" && activeSubFilter === "audiobooks");
        const isEbook = currentView === "ebooks" || (currentView === "all" && activeSubFilter === "ebooks");
        const isTbr = currentView === "tbr";
        container.innerHTML = `
          <div class="empty-state">
            <h2>${
              isAudio ? "No audiobooks in this view" :
              isEbook ? "No ebooks in this view" :
              isTbr ? "Your 'To Be Read' list is empty" :
              "No books in this view yet"
            }</h2>
            <p>${
              isAudio
                ? "Upload an audiobook file (.m4b, .mp3, .m4a, .flac) to stream it right in your browser or download it to your phone! We'll automatically pull the narrator, runtime, cover art, and summary from Audible."
                : (isEbook
                  ? "Upload an ebook file (.epub, .pdf, .mobi, .azw3) to read, download, or send wirelessly to your Kindle."
                  : (isTbr
                    ? "Add books or audiobooks you want to read! They stay separate from your owned shelves until you upload the file."
                    : "Upload an ebook or audiobook file, or add a book to your TBR list to get started."))
            }</p>
            <div style="display:flex; gap:0.65rem; justify-content:center; flex-wrap:wrap;">
              ${
                isAudio
                  ? `<button class="btn btn-cyan" onclick="openUploadModal('audiobook')">🎧 Upload Audiobook</button>`
                  : (isEbook
                    ? `<button class="btn btn-primary" onclick="openUploadModal('ebook')">＋ Upload Ebook</button>`
                    : `<button class="btn btn-primary" onclick="openUploadModal('ebook')">＋ Upload Ebook</button>
                       <button class="btn btn-cyan" onclick="openUploadModal('audiobook')">🎧 Upload Audiobook</button>
                       <button class="btn btn-amber" onclick="openTbrModal()">🔖 Add to TBR (No File)</button>`
                  )
              }
            </div>
          </div>
        `;
        return;
      }

      container.innerHTML = `<div class="book-grid">${books.map(b => renderSingleBookCard(b)).join("")}</div>`;
    }

    function renderSingleBookCard(book) {
      const isRead = book.is_read || book.reading_status === "read";
      const isTbr = book.reading_status === "tbr" && !isRead;
      const isAudio = book.media_type === "audiobook";
      const ext = book.has_file
        ? (book.filename.split(".").pop() || "FILE").toUpperCase()
        : (isAudio ? "WISHLIST AUDIO" : "WISHLIST EBOOK");

      const ribbonHtml = isRead
        ? `<div class="read-ribbon">✓ Read</div>`
        : (isTbr ? `<div class="tbr-ribbon">🔖 TBR</div>` : "");

      const coverHtml = book.cover_url
        ? `<img src="${escapeHtml(book.cover_url)}" alt="${escapeHtml(book.title)}" onerror="this.parentElement.innerHTML='<div class=\\'cover-fallback\\'>${escapeHtml(book.title)}</div>'" />`
        : `<div class="cover-fallback">${escapeHtml(book.title)}</div>`;

      const seriesBadge = book.series_name
        ? `<span class="badge badge-series" onclick="switchView('series')" title="View Series">📖 ${escapeHtml(book.series_name)}${book.series_number ? ` #${escapeHtml(book.series_number)}` : ""}</span>`
        : "";

      const starsHtml = [1, 2, 3, 4, 5].map(num => `
        <button class="star-btn ${book.rating >= num ? 'filled' : ''}" onclick="quickRate(${book.id}, ${book.rating === num ? 0 : num})" title="Rate ${num} star(s)">★</button>
      `).join("");

      return `
        <div class="book-card ${isRead ? 'is-read-card' : ''}">
          <div class="book-card-top">
            <div class="cover-wrap ${isAudio ? 'audiobook-cover' : ''}">
              ${ribbonHtml}
              ${coverHtml}
            </div>
            <div class="book-info">
              <div class="badges-row">
                <span class="badge">ID #${book.id}</span>
                <span class="badge ${isAudio ? 'badge-audio' : (book.has_file ? 'badge-muted' : 'badge-tbr-nofile')}">
                  ${isAudio ? "🎧 " : ""}${escapeHtml(ext)}
                </span>
                ${book.duration ? `<span class="badge badge-audio">⏱️ ${escapeHtml(book.duration)}</span>` : ""}
                ${seriesBadge}
                ${book.published_year ? `<span class="badge badge-muted">${escapeHtml(book.published_year)}</span>` : ""}
              </div>
              <div class="book-title">${escapeHtml(book.title)}</div>
              <div class="book-author" onclick="switchView('authors', '${escapeHtml(book.author).replace(/'/g, "\\'")}')">${escapeHtml(book.author)}</div>
              ${book.narrator ? `<div class="book-narrator">🎙️ Narrated by ${escapeHtml(book.narrator)}</div>` : ""}

              <div class="stars-row" title="Click to rate 1–5 stars">
                ${starsHtml}
                <span style="font-size:0.73rem; color:var(--text-muted); margin-left:0.35rem;">
                  ${book.rating ? `${book.rating}/5` : "Rate"}
                </span>
              </div>
            </div>
          </div>

          ${book.review_headline ? `<div class="review-snippet" style="font-style:italic; color:#e0e7ff; cursor:pointer;" onclick="openReviewModal(${book.id})" title="Click to view/edit review">“${escapeHtml(book.review_headline)}”</div>` : ""}
          ${book.review ? `<div class="review-snippet" style="cursor:pointer;" onclick="openReviewModal(${book.id})" title="Click to view/edit review">💬 <strong>Review:</strong> ${escapeHtml(book.review)}</div>` : ""}
          ${book.favorite_characters ? `<div class="review-snippet" style="color:#d8b4fe; cursor:pointer;" onclick="openReviewModal(${book.id})" title="Click to view/edit review">👥 <strong>Characters:</strong> ${escapeHtml(book.favorite_characters)}</div>` : ""}

          <div class="book-desc">
            ${book.description ? escapeHtml(book.description) : "<em>No synopsis yet. Click 'Edit' to fetch metadata.</em>"}
          </div>

          <div class="book-actions">
            ${isAudio && book.has_file
              ? `<button class="btn btn-cyan btn-sm" onclick="playAudiobook(${book.id})">▶ Listen</button>`
              : ""
            }

            <button
              class="btn btn-sm ${isRead ? 'btn-read-active' : 'btn-secondary'}"
              onclick="toggleReadStatus(${book.id}, ${!isRead})"
              title="Toggle Read / Finished status"
            >
              ${isRead ? "✅ Read" : "○ Mark Read"}
            </button>

            <button
              class="btn btn-sm ${isTbr ? 'btn-tbr-active' : 'btn-secondary'}"
              onclick="toggleTbrStatus(${book.id}, '${isTbr ? 'unread' : 'tbr'}')"
              title="Add or remove from To Be Read list"
            >
              ${isTbr ? "🔖 On TBR" : "＋ TBR"}
            </button>

            ${book.has_file
              ? `<a class="btn btn-emerald btn-sm" href="/books/${book.id}/download">⬇ Download</a>
                 <button class="btn btn-secondary btn-sm" onclick="openSendDeviceModal(${book.id})" title="Send to Kindle, Phone, or Tablet">📤 Send to Device</button>`
              : `<button class="btn btn-secondary btn-sm" onclick="triggerAttachFile(${book.id})">📎 Attach File</button>`
            }

            <button class="btn btn-secondary btn-sm" onclick="openReviewModal(${book.id})" title="Write or edit review, quotes, and characters">💬 Review</button>
            <button class="btn btn-secondary btn-sm" onclick="openEditModal(${book.id})" title="Edit book details">✏️ Edit</button>
            ${book.has_file ? `<button class="btn btn-secondary btn-sm" onclick="promptRename(${book.id}, '${escapeHtml(book.filename).replace(/'/g, "\\'")}')" title="Rename File">🏷️</button>` : ""}
            <button class="btn btn-danger btn-sm" onclick="confirmDelete(${book.id}, '${escapeHtml(book.title).replace(/'/g, "\\'")}')">🗑️</button>
          </div>
        </div>
      `;
    }

    // --- IN-BROWSER AUDIOBOOK PLAYER ---
    function playAudiobook(bookId) {
      const book = allBooks.find(b => b.id === bookId);
      if (!book) return;
      const bar = document.getElementById("audioPlayerBar");
      const audio = document.getElementById("audioElement");
      const cover = document.getElementById("playerCover");

      document.getElementById("playerTitle").textContent = book.title;
      document.getElementById("playerSub").textContent = book.narrator
        ? `🎙️ ${book.narrator} • ${book.author}`
        : book.author;

      if (book.cover_url) {
        cover.src = book.cover_url;
        cover.style.display = "block";
      } else {
        cover.style.display = "none";
      }

      audio.src = `/books/${book.id}/stream`;
      audio.playbackRate = parseFloat(document.getElementById("playbackSpeed").value || "1");
      bar.classList.add("open");
      audio.play().catch(() => {});
    }

    function setAudioSpeed(val) {
      const audio = document.getElementById("audioElement");
      audio.playbackRate = parseFloat(val || "1");
    }

    function closeAudioPlayer() {
      const bar = document.getElementById("audioPlayerBar");
      const audio = document.getElementById("audioElement");
      audio.pause();
      audio.src = "";
      bar.classList.remove("open");
    }

    // --- QUICK ACTIONS ---
    async function toggleReadStatus(bookId, markAsRead) {
      const res = await fetch(`/books/${bookId}/status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_read: markAsRead })
      });
      if (res.ok) {
        showToast(markAsRead ? "Marked as Read! ✅" : "Marked as Unread");
        loadBooks(document.getElementById("searchInput").value);
      }
    }

    async function toggleTbrStatus(bookId, newStatus) {
      const res = await fetch(`/books/${bookId}/status`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reading_status: newStatus })
      });
      if (res.ok) {
        showToast(newStatus === "tbr" ? "Added to your TBR list! 🔖" : "Removed from TBR");
        loadBooks(document.getElementById("searchInput").value);
      }
    }

    async function quickRate(bookId, stars) {
      const res = await fetch(`/books/${bookId}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rating: stars })
      });
      if (res.ok) {
        showToast(stars ? `Rated ${stars} ★` : "Cleared rating");
        loadBooks(document.getElementById("searchInput").value);
      }
    }

    function triggerAttachFile(bookId) {
      attachTargetBookId = bookId;
      const input = document.getElementById("attachFileInput");
      input.value = "";
      input.click();
    }

    async function handleAttachFileSelected(input) {
      if (!input.files || !input.files[0] || !attachTargetBookId) return;
      const formData = new FormData();
      formData.append("file", input.files[0]);

      showToast("Attaching file...");
      const res = await fetch(`/books/${attachTargetBookId}/attach-file`, {
        method: "POST",
        body: formData
      });
      const data = await res.json();
      if (!res.ok) {
        alert(data.detail || "Failed to attach file");
        return;
      }
      showToast(`Attached "${data.filename}"!`);
      loadBooks(document.getElementById("searchInput").value);
    }

    // --- CANDIDATE LIST RENDERER ---
    function renderCandidateList(items, selectFnName) {
      return items.map((item, idx) => `
        <div class="lookup-item" onclick="${selectFnName}(${idx})">
          ${item.cover_url
            ? `<img src="${escapeHtml(item.cover_url)}" alt="" />`
            : `<div style="width:38px;height:56px;background:#312e81;border-radius:4px;display:flex;align-items:center;justify-content:center;font-size:0.75rem;flex-shrink:0;">📘</div>`
          }
          <div class="lookup-item-info">
            <div class="lookup-item-title">
              ${escapeHtml(item.title)}
              ${item.series_name ? `<span class="badge badge-series" style="margin-left:4px;">${escapeHtml(item.series_name)}${item.series_number ? ` #${escapeHtml(item.series_number)}` : ""}</span>` : ""}
            </div>
            <div class="lookup-item-sub">
              <span class="badge" style="margin-right:4px;">${escapeHtml(item.source || "Online")}</span>
              ${escapeHtml(item.author)}
              ${item.narrator ? ` • 🎙️ ${escapeHtml(item.narrator)}` : ""}
              ${item.duration ? ` • ⏱️ ${escapeHtml(item.duration)}` : ""}
            </div>
            ${item.description ? `<div class="lookup-item-desc">${escapeHtml(item.description)}</div>` : ""}
          </div>
          <span class="badge">Use This</span>
        </div>
      `).join("");
    }

    // --- 1. UPLOAD FILE MODAL ---
    function openUploadModal(defaultType = "ebook") {
      document.getElementById("uploadForm").reset();
      document.getElementById("lookupResults").innerHTML = "";
      document.getElementById("metaMediaType").value = defaultType;
      document.getElementById("lookupSource").value = defaultType === "audiobook" ? "amazon" : "all";
      document.getElementById("uploadModalHeading").textContent = defaultType === "audiobook"
        ? "🎧 Upload Audiobook & Fetch Audible Metadata"
        : "📚 Upload Ebook & Fetch Metadata";
      const banner = document.getElementById("epubBanner");
      banner.style.display = "none";
      document.getElementById("uploadModal").classList.add("open");
    }

    function onMediaTypeChanged() {
      const t = document.getElementById("metaMediaType").value;
      if (t === "audiobook") {
        document.getElementById("lookupSource").value = "amazon";
      }
    }

    function closeUploadModal() {
      document.getElementById("uploadModal").classList.remove("open");
    }

    async function onFileSelected(input) {
      if (!input.files || !input.files[0]) return;
      const file = input.files[0];
      const banner = document.getElementById("epubBanner");
      banner.style.display = "block";
      banner.textContent = "Inspecting file...";

      const formData = new FormData();
      formData.append("file", file);

      try {
        const res = await fetch("/books/extract-file-metadata", { method: "POST", body: formData });
        if (res.ok) {
          const data = await res.json();
          const emb = data.embedded || {};
          document.getElementById("lookupQuery").value = data.suggested_query || "";

          if (data.media_type === "audiobook") {
            document.getElementById("metaMediaType").value = "audiobook";
            document.getElementById("lookupSource").value = "amazon";
            banner.innerHTML = `🎧 Detected Audiobook file — searching Audible for narrator, runtime & cover art...`;
          } else if (emb.title || emb.author) {
            banner.innerHTML = `✅ Found inside EPUB: <strong>${escapeHtml(emb.title || "Untitled")}</strong> by <strong>${escapeHtml(emb.author || "Unknown")}</strong> — searching online...`;
            if (emb.title) document.getElementById("metaTitle").value = emb.title;
            if (emb.author) document.getElementById("metaAuthor").value = emb.author;
            if (emb.isbn) document.getElementById("metaIsbn").value = emb.isbn;
            if (emb.published_year) document.getElementById("metaYear").value = emb.published_year;
            if (emb.series_name) document.getElementById("metaSeries").value = emb.series_name;
            if (emb.series_number) document.getElementById("metaSeriesNum").value = emb.series_number;
            if (emb.description) document.getElementById("metaDesc").value = emb.description;
          } else {
            banner.textContent = `Cleaned search query: "${data.suggested_query}". Searching online...`;
          }

          if (data.suggested_query) {
            await previewOnlineMetadata(false);
          }
        }
      } catch (err) {
        banner.style.display = "none";
      }
    }

    async function previewOnlineMetadata(overwriteExisting = true) {
      const q = document.getElementById("lookupQuery").value.trim();
      const source = document.getElementById("lookupSource").value;
      if (!q) return;
      const btn = document.getElementById("lookupBtn");
      const resultsEl = document.getElementById("lookupResults");
      btn.disabled = true;
      btn.textContent = "Searching...";
      resultsEl.innerHTML = `<div style="font-size:0.8rem; color:var(--text-muted);">Searching online...</div>`;

      try {
        const res = await fetch(`/books/lookup-online?q=${encodeURIComponent(q)}&source=${encodeURIComponent(source)}`);
        if (!res.ok) {
          resultsEl.innerHTML = `<div style="font-size:0.8rem; color:#fca5a5;">No matches found. Try Title + Author.</div>`;
          return;
        }
        const data = await res.json();
        const items = data.results || [data.found];
        window._lastCandidates = items;
        resultsEl.innerHTML = renderCandidateList(items, "selectCandidate");
        if (items[0]) selectCandidate(0, false, overwriteExisting);
      } finally {
        btn.disabled = false;
        btn.textContent = "🔎 Search";
      }
    }

    function selectCandidate(idx, notify = true, overwriteAll = true) {
      const item = (window._lastCandidates || [])[idx];
      if (!item) return;
      if (overwriteAll || !document.getElementById("metaTitle").value) document.getElementById("metaTitle").value = item.title || "";
      if (overwriteAll || !document.getElementById("metaAuthor").value) document.getElementById("metaAuthor").value = item.author || "";
      if (overwriteAll || !document.getElementById("metaNarrator").value) document.getElementById("metaNarrator").value = item.narrator || "";
      if (overwriteAll || !document.getElementById("metaDuration").value) document.getElementById("metaDuration").value = item.duration || "";
      if (overwriteAll || !document.getElementById("metaIsbn").value) document.getElementById("metaIsbn").value = item.isbn || "";
      if (overwriteAll || !document.getElementById("metaYear").value) document.getElementById("metaYear").value = item.published_year || "";
      if (overwriteAll || !document.getElementById("metaSeries").value) document.getElementById("metaSeries").value = item.series_name || "";
      if (overwriteAll || !document.getElementById("metaSeriesNum").value) document.getElementById("metaSeriesNum").value = item.series_number || "";
      if (item.cover_url) document.getElementById("metaCover").value = item.cover_url;
      if (overwriteAll || !document.getElementById("metaDesc").value) {
        if (item.description) document.getElementById("metaDesc").value = item.description;
      }
      document.getElementById("metaSource").value = item.source || "";
      if (notify) showToast(`Selected "${item.title}"`);
    }

    async function submitUpload(e) {
      e.preventDefault();
      const fileInput = document.getElementById("bookFile");
      if (!fileInput.files.length) return;

      const btn = document.getElementById("uploadSubmitBtn");
      btn.disabled = true;
      btn.textContent = "Uploading...";

      const formData = new FormData();
      formData.append("file", fileInput.files[0]);
      formData.append("lookup_query", document.getElementById("lookupQuery").value.trim());
      formData.append("metadata_source", document.getElementById("lookupSource").value);
      formData.append("media_type_override", document.getElementById("metaMediaType").value);
      formData.append("reading_status_override", document.getElementById("metaStatus").value);

      const fields = [
        ["custom_filename", "customFilename"],
        ["title_override", "metaTitle"],
        ["author_override", "metaAuthor"],
        ["narrator_override", "metaNarrator"],
        ["duration_override", "metaDuration"],
        ["description_override", "metaDesc"],
        ["isbn_override", "metaIsbn"],
        ["cover_url_override", "metaCover"],
        ["published_year_override", "metaYear"],
        ["series_name_override", "metaSeries"],
        ["series_number_override", "metaSeriesNum"],
        ["source_override", "metaSource"],
      ];
      for (const [key, id] of fields) {
        const val = document.getElementById(id).value.trim();
        if (val) formData.append(key, val);
      }

      try {
        const res = await fetch("/books/upload-smart", { method: "POST", body: formData });
        const data = await res.json();
        if (!res.ok) {
          alert(data.detail || "Upload failed");
          return;
        }
        closeUploadModal();
        showToast(`Uploaded "${data.populated_metadata.title}"!`);
        if (data.populated_metadata.media_type === "audiobook") {
          switchView("audiobooks");
        }
        loadBooks(document.getElementById("searchInput").value);
      } finally {
        btn.disabled = false;
        btn.textContent = "🚀 Upload & Save";
      }
    }

    // --- 2. TBR (NO FILE) MODAL ---
    function openTbrModal() {
      document.getElementById("tbrForm").reset();
      document.getElementById("tbrLookupResults").innerHTML = "";
      document.getElementById("tbrModal").classList.add("open");
    }

    function closeTbrModal() {
      document.getElementById("tbrModal").classList.remove("open");
    }

    async function previewTbrMetadata() {
      const q = document.getElementById("tbrLookupQuery").value.trim();
      const source = document.getElementById("tbrLookupSource").value;
      if (!q) return;
      const btn = document.getElementById("tbrLookupBtn");
      const resultsEl = document.getElementById("tbrLookupResults");
      btn.disabled = true;
      btn.textContent = "Searching...";
      resultsEl.innerHTML = `<div style="font-size:0.8rem; color:var(--text-muted);">Searching online...</div>`;

      try {
        const res = await fetch(`/books/lookup-online?q=${encodeURIComponent(q)}&source=${encodeURIComponent(source)}`);
        if (!res.ok) {
          resultsEl.innerHTML = `<div style="font-size:0.8rem; color:#fca5a5;">No matches found.</div>`;
          return;
        }
        const data = await res.json();
        const items = data.results || [data.found];
        window._tbrCandidates = items;
        resultsEl.innerHTML = renderCandidateList(items, "selectTbrCandidate");
        if (items[0]) selectTbrCandidate(0, false);
      } finally {
        btn.disabled = false;
        btn.textContent = "🔎 Search";
      }
    }

    function selectTbrCandidate(idx, notify = true) {
      const item = (window._tbrCandidates || [])[idx];
      if (!item) return;
      document.getElementById("tbrTitle").value = item.title || "";
      document.getElementById("tbrAuthor").value = item.author || "";
      document.getElementById("tbrNarrator").value = item.narrator || "";
      document.getElementById("tbrDuration").value = item.duration || "";
      document.getElementById("tbrSeries").value = item.series_name || "";
      document.getElementById("tbrSeriesNum").value = item.series_number || "";
      document.getElementById("tbrCover").value = item.cover_url || "";
      document.getElementById("tbrYear").value = item.published_year || "";
      document.getElementById("tbrIsbn").value = item.isbn || "";
      document.getElementById("tbrDesc").value = item.description || "";
      document.getElementById("tbrSource").value = item.source || "";
      if (notify) showToast(`Selected "${item.title}"`);
    }

    async function submitTbrBook(e) {
      e.preventDefault();
      const payload = {
        title: document.getElementById("tbrTitle").value,
        author: document.getElementById("tbrAuthor").value,
        media_type: document.getElementById("tbrMediaType").value,
        narrator: document.getElementById("tbrNarrator").value,
        duration: document.getElementById("tbrDuration").value,
        series_name: document.getElementById("tbrSeries").value,
        series_number: document.getElementById("tbrSeriesNum").value,
        reading_status: "tbr",
        cover_url: document.getElementById("tbrCover").value,
        published_year: document.getElementById("tbrYear").value,
        isbn: document.getElementById("tbrIsbn").value,
        description: document.getElementById("tbrDesc").value,
        source: document.getElementById("tbrSource").value
      };

      const res = await fetch("/books/add-without-file", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        closeTbrModal();
        showToast(`Added "${payload.title}" to your TBR list! 🔖`);
        loadBooks(document.getElementById("searchInput").value);
      }
    }

    // --- 3. EDIT / REVIEW MODAL ---
    function openEditModal(bookId) {
      const book = allBooks.find(b => b.id === bookId);
      if (!book) return;
      document.getElementById("editBookId").value = book.id;
      document.getElementById("editModalTitle").textContent = `Edit #${book.id}: ${book.title}`;
      document.getElementById("editTitle").value = book.title || "";
      document.getElementById("editAuthor").value = book.author || "";
      document.getElementById("editMediaType").value = book.media_type || "ebook";
      document.getElementById("editNarrator").value = book.narrator || "";
      document.getElementById("editDuration").value = book.duration || "";
      document.getElementById("editSeries").value = book.series_name || "";
      document.getElementById("editSeriesNum").value = book.series_number || "";
      document.getElementById("editStatus").value = book.is_read ? "read" : (book.reading_status || "unread");
      document.getElementById("editRating").value = String(book.rating || 0);
      document.getElementById("editReview").value = book.review || "";
      document.getElementById("editIsbn").value = book.isbn || "";
      document.getElementById("editYear").value = book.published_year || "";
      document.getElementById("editCover").value = book.cover_url || "";
      document.getElementById("editDesc").value = book.description || "";
      document.getElementById("editSource").value = book.source || "";
      document.getElementById("editLookupQuery").value = `${book.title || ""} ${book.author && book.author !== "Unknown Author" ? book.author : ""}`.trim();
      document.getElementById("editLookupResults").innerHTML = "";
      document.getElementById("editModal").classList.add("open");
    }

    function closeEditModal() {
      document.getElementById("editModal").classList.remove("open");
    }

    async function previewEditMetadata() {
      const q = document.getElementById("editLookupQuery").value.trim();
      const source = document.getElementById("editLookupSource").value;
      if (!q) return;
      const btn = document.getElementById("editLookupBtn");
      const resultsEl = document.getElementById("editLookupResults");
      btn.disabled = true;
      btn.textContent = "Searching...";

      try {
        const res = await fetch(`/books/lookup-online?q=${encodeURIComponent(q)}&source=${encodeURIComponent(source)}`);
        if (!res.ok) {
          resultsEl.innerHTML = `<div style="font-size:0.8rem; color:#fca5a5;">No matches found.</div>`;
          return;
        }
        const data = await res.json();
        const items = data.results || [data.found];
        window._editCandidates = items;
        resultsEl.innerHTML = renderCandidateList(items, "selectEditCandidate");
      } finally {
        btn.disabled = false;
        btn.textContent = "🔎 Search";
      }
    }

    function selectEditCandidate(idx) {
      const item = (window._editCandidates || [])[idx];
      if (!item) return;
      document.getElementById("editTitle").value = item.title || "";
      document.getElementById("editAuthor").value = item.author || "";
      if (item.narrator) document.getElementById("editNarrator").value = item.narrator;
      if (item.duration) document.getElementById("editDuration").value = item.duration;
      if (item.series_name) document.getElementById("editSeries").value = item.series_name;
      if (item.series_number) document.getElementById("editSeriesNum").value = item.series_number;
      document.getElementById("editIsbn").value = item.isbn || "";
      document.getElementById("editYear").value = item.published_year || "";
      document.getElementById("editCover").value = item.cover_url || "";
      document.getElementById("editDesc").value = item.description || "";
      document.getElementById("editSource").value = item.source || "";
      showToast(`Filled from ${item.source || "online"}!`);
    }

    async function submitEdit(e) {
      e.preventDefault();
      const bookId = document.getElementById("editBookId").value;
      const payload = {
        title: document.getElementById("editTitle").value,
        author: document.getElementById("editAuthor").value,
        media_type: document.getElementById("editMediaType").value,
        narrator: document.getElementById("editNarrator").value,
        duration: document.getElementById("editDuration").value,
        series_name: document.getElementById("editSeries").value,
        series_number: document.getElementById("editSeriesNum").value,
        reading_status: document.getElementById("editStatus").value,
        rating: parseInt(document.getElementById("editRating").value || "0", 10),
        review: document.getElementById("editReview").value,
        isbn: document.getElementById("editIsbn").value,
        published_year: document.getElementById("editYear").value,
        cover_url: document.getElementById("editCover").value,
        description: document.getElementById("editDesc").value,
        source: document.getElementById("editSource").value
      };

      const res = await fetch(`/books/${bookId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        closeEditModal();
        showToast("Saved changes!");
        loadBooks(document.getElementById("searchInput").value);
      }
    }

    async function promptRename(bookId, currentFilename) {
      const newName = prompt(`Enter new filename for Book #${bookId}:`, currentFilename);
      if (!newName || newName.trim() === currentFilename) return;
      const formData = new FormData();
      formData.append("new_filename", newName.trim());
      const res = await fetch(`/books/${bookId}/rename`, { method: "POST", body: formData });
      const data = await res.json();
      if (!res.ok) {
        alert(data.detail || "Rename failed");
        return;
      }
      showToast(`Renamed file to "${data.new_filename}"`);
      loadBooks(document.getElementById("searchInput").value);
    }

    async function confirmDelete(bookId, title) {
      if (!confirm(`Delete "${title}" (ID #${bookId})?`)) return;
      const res = await fetch(`/books/${bookId}`, { method: "DELETE" });
      if (res.ok) {
        showToast(`Deleted Book #${bookId}`);
        loadBooks(document.getElementById("searchInput").value);
      }
    }

    // --- MASS / BATCH UPLOAD LOGIC ---
    let massQueue = [];
    let massUploadActive = false;
    let massCancelRequested = false;

    function openMassUploadModal() {
      document.getElementById("massUploadModal").classList.add("open");
      initMassDropzone();
      renderMassQueueUI();
    }

    function closeMassUploadModal() {
      if (massUploadActive) {
        if (!confirm("A mass upload is currently running. Close and stop?")) return;
        massCancelRequested = true;
      }
      document.getElementById("massUploadModal").classList.remove("open");
    }

    function triggerMassFileSelect() {
      document.getElementById("massFileInput").value = "";
      document.getElementById("massFileInput").click();
    }

    function triggerMassFolderSelect() {
      document.getElementById("massFolderInput").value = "";
      document.getElementById("massFolderInput").click();
    }

    function initMassDropzone() {
      const dropzone = document.getElementById("massDropzone");
      if (!dropzone || dropzone._inited) return;
      dropzone._inited = true;

      ['dragenter', 'dragover'].forEach(name => {
        dropzone.addEventListener(name, (e) => {
          e.preventDefault();
          e.stopPropagation();
          dropzone.classList.add('dragover');
        }, false);
      });

      ['dragleave', 'drop'].forEach(name => {
        dropzone.addEventListener(name, (e) => {
          e.preventDefault();
          e.stopPropagation();
          dropzone.classList.remove('dragover');
        }, false);
      });

      dropzone.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        if (dt && dt.files && dt.files.length) {
          handleMassFilesSelected(dt.files);
        }
      });
    }

    function formatBytes(bytes) {
      if (!bytes || bytes === 0) return '0 B';
      const k = 1024;
      const sizes = ['B', 'KB', 'MB', 'GB'];
      const i = Math.floor(Math.log(bytes) / Math.log(k));
      return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }

    const AUDIO_FILE_EXTS = new Set([".m4b", ".mp3", ".m4a", ".flac", ".ogg", ".opus", ".aac", ".wav"]);

    function handleMassFilesSelected(filesList) {
      if (!filesList || !filesList.length) return;

      for (let i = 0; i < filesList.length; i++) {
        const f = filesList[i];
        if (f.name.startsWith(".") || f.name.toLowerCase() === "desktop.ini") continue;

        const ext = "." + (f.name.split(".").pop() || "").toLowerCase();
        const isAudio = AUDIO_FILE_EXTS.has(ext);

        if (!massQueue.some(item => item.file.name === f.name && item.file.size === f.size)) {
          massQueue.push({
            id: "q_" + Math.random().toString(36).substring(2, 9),
            file: f,
            isAudio: isAudio,
            status: "pending",
            resultTitle: "",
            resultAuthor: "",
            message: "Waiting in queue"
          });
        }
      }

      renderMassQueueUI();
    }

    function renderMassQueueUI() {
      const listEl = document.getElementById("massQueueList");
      const summaryEl = document.getElementById("massQueueSummary");
      const startBtn = document.getElementById("massStartBtn");

      const total = massQueue.length;
      const completed = massQueue.filter(q => q.status === "success").length;
      const skipped = massQueue.filter(q => q.status === "skipped").length;
      const errors = massQueue.filter(q => q.status === "error").length;
      const pending = massQueue.filter(q => q.status === "pending").length;

      if (total === 0) {
        summaryEl.textContent = "No files selected yet.";
        listEl.innerHTML = "";
        startBtn.disabled = true;
        return;
      }

      startBtn.disabled = pending === 0 && !massUploadActive;
      summaryEl.innerHTML = `<strong>${total}</strong> file(s) in queue • <span style="color:#6ee7b7;">${completed} uploaded</span> • <span style="color:#fcd34d;">${skipped} skipped</span> • <span style="color:#fca5a5;">${errors} errors</span>`;

      listEl.innerHTML = massQueue.map(item => {
        let statusClass = "queue-status-pending";
        let statusIcon = "⏳";
        let statusText = item.message;

        if (item.status === "active") {
          statusClass = "queue-status-active";
          statusIcon = "🔄";
          statusText = "Uploading & fetching metadata...";
        } else if (item.status === "success") {
          statusClass = "queue-status-success";
          statusIcon = "✅";
          statusText = item.resultTitle ? `Saved: "${item.resultTitle}"` : "Uploaded successfully";
        } else if (item.status === "skipped") {
          statusClass = "queue-status-skipped";
          statusIcon = "⚠️";
          statusText = item.message || "Skipped (already exists)";
        } else if (item.status === "error") {
          statusClass = "queue-status-error";
          statusIcon = "❌";
          statusText = "Error: " + item.message;
        }

        return `
          <div class="mass-queue-item">
            <div style="display:flex; align-items:center; gap:0.5rem; min-width:0; flex:1;">
              <span style="font-size:1.1rem;">${item.isAudio ? "🎧" : "📚"}</span>
              <div style="min-width:0;">
                <div style="font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
                  ${escapeHtml(item.file.name)}
                </div>
                <div style="font-size:0.72rem; color:var(--text-muted);">
                  ${formatBytes(item.file.size)}
                </div>
              </div>
            </div>
            <div class="${statusClass}" style="flex-shrink:0; max-width:280px; text-align:right; font-size:0.78rem;">
              ${statusIcon} ${escapeHtml(statusText)}
            </div>
          </div>
        `;
      }).join("");
    }

    function clearMassQueue() {
      if (massUploadActive) return;
      massQueue = [];
      document.getElementById("massProgressTrack").style.display = "none";
      document.getElementById("massProgressLabel").style.display = "none";
      renderMassQueueUI();
    }

    function cancelMassUpload() {
      massCancelRequested = true;
      document.getElementById("massCancelBtn").textContent = "Stopping...";
    }

    async function startMassUpload() {
      if (massUploadActive) return;
      const pendingItems = massQueue.filter(item => item.status === "pending");
      if (!pendingItems.length) return;

      massUploadActive = true;
      massCancelRequested = false;

      const startBtn = document.getElementById("massStartBtn");
      const cancelBtn = document.getElementById("massCancelBtn");
      const clearBtn = document.getElementById("massClearBtn");
      const progressTrack = document.getElementById("massProgressTrack");
      const progressFill = document.getElementById("massProgressFill");
      const progressLabel = document.getElementById("massProgressLabel");

      startBtn.style.display = "none";
      cancelBtn.style.display = "inline-flex";
      cancelBtn.textContent = "⏹ Stop Upload";
      clearBtn.disabled = true;
      progressTrack.style.display = "block";
      progressLabel.style.display = "block";

      const totalCount = massQueue.length;
      let processedCount = massQueue.filter(item => item.status !== "pending").length;

      const mediaSetting = document.getElementById("massMediaType").value;
      const metaSource = document.getElementById("massMetadataSource").value;
      const duplicateAction = document.getElementById("massDuplicateAction").value;
      const readingStatus = document.getElementById("massReadingStatus").value;

      for (const item of massQueue) {
        if (massCancelRequested) {
          break;
        }
        if (item.status !== "pending") {
          continue;
        }

        item.status = "active";
        renderMassQueueUI();

        const percent = Math.round((processedCount / totalCount) * 100);
        progressFill.style.width = `${percent}%`;
        progressLabel.textContent = `Processing ${processedCount + 1} of ${totalCount} (${percent}%): ${item.file.name}`;

        try {
          const formData = new FormData();
          formData.append("file", item.file);
          formData.append("metadata_source", metaSource);
          formData.append("reading_status_override", readingStatus);

          if (mediaSetting === "audiobook") {
            formData.append("media_type_override", "audiobook");
          } else if (mediaSetting === "ebook") {
            formData.append("media_type_override", "ebook");
          }

          if (duplicateAction === "skip") {
            formData.append("skip_if_exists", "true");
          } else if (duplicateAction === "rename") {
            formData.append("auto_rename_if_exists", "true");
          }

          const res = await fetch("/books/upload-smart", {
            method: "POST",
            body: formData
          });
          const data = await res.json();

          if (!res.ok) {
            item.status = "error";
            item.message = data.detail || "Upload error";
          } else if (data.status === "skipped") {
            item.status = "skipped";
            item.message = data.message || "File already exists (skipped)";
          } else {
            item.status = "success";
            const meta = data.populated_metadata || {};
            item.resultTitle = meta.title || item.file.name;
            item.resultAuthor = meta.author || "";
            item.message = `Saved: "${item.resultTitle}"`;
          }
        } catch (err) {
          item.status = "error";
          item.message = err.message || "Network error";
        }

        processedCount++;
        const finalPct = Math.round((processedCount / totalCount) * 100);
        progressFill.style.width = `${finalPct}%`;
        renderMassQueueUI();
      }

      massUploadActive = false;
      startBtn.style.display = "inline-flex";
      cancelBtn.style.display = "none";
      clearBtn.disabled = false;

      const successCount = massQueue.filter(i => i.status === "success").length;
      const skipCount = massQueue.filter(i => i.status === "skipped").length;

      if (massCancelRequested) {
        progressLabel.textContent = `Stopped. Uploaded ${successCount}, skipped ${skipCount}.`;
        showToast(`Mass upload stopped. ${successCount} added.`);
      } else {
        progressFill.style.width = "100%";
        progressLabel.textContent = `Complete! ${successCount} uploaded, ${skipCount} skipped.`;
        showToast(`Mass upload complete! ${successCount} added.`);
      }

      await loadBooks(document.getElementById("searchInput").value);
    }

    // --- SEND TO DEVICE & KINDLE LOGIC ---
    let activeSendBookId = null;
    let cachedDeviceInfo = null;

    async function fetchDeviceInfo() {
      try {
        const res = await fetch("/system/device-info");
        if (res.ok) {
          cachedDeviceInfo = await res.json();
          return cachedDeviceInfo;
        }
      } catch (e) {}
      return null;
    }

    async function openSendDeviceModal(bookId) {
      const book = allBooks.find(b => b.id === bookId);
      if (!book) return;
      activeSendBookId = bookId;

      const modal = document.getElementById("sendDeviceModal");
      document.getElementById("sendBookName").textContent = `${book.title} — ${book.author}`;
      document.getElementById("sendDeviceModalTitle").textContent = `📤 Send to Device: "${book.title}"`;
      document.getElementById("sendKindleStatusMsg").style.display = "none";

      const info = await fetchDeviceInfo();
      const localIp = info?.local_ip || window.location.hostname;
      const port = info?.port || window.location.port || "8000";
      const downloadUrl = `http://${localIp}:${port}/books/${book.id}/download`;

      document.getElementById("sendDeviceUrl").value = downloadUrl;
      document.getElementById("opdsFeedUrl").value = info?.opds_url || `http://${localIp}:${port}/opds`;

      const qrUrl = `https://api.qrserver.com/v1/create-qr-code/?size=220x220&data=${encodeURIComponent(downloadUrl)}`;
      document.getElementById("deviceQrImage").src = qrUrl;

      const savedKindle = info?.settings?.kindle_email || "";
      document.getElementById("sendKindleEmailInput").value = savedKindle;

      switchSendTab("qr");
      modal.classList.add("open");
    }

    function closeSendDeviceModal() {
      document.getElementById("sendDeviceModal").classList.remove("open");
    }

    function switchSendTab(tab) {
      ["qr", "kindle", "opds"].forEach(t => {
        const el = document.getElementById(`sendTab-${t}`);
        const btn = document.getElementById(`tabBtn-${t}`);
        if (el) el.style.display = t === tab ? "block" : "none";
        if (btn) {
          if (t === tab) btn.classList.add("active");
          else btn.classList.remove("active");
        }
      });
    }

    function copyDeviceUrl() {
      const input = document.getElementById("sendDeviceUrl");
      input.select();
      navigator.clipboard.writeText(input.value);
      showToast("Download link copied to clipboard!");
    }

    function copyOpdsUrl() {
      const input = document.getElementById("opdsFeedUrl");
      input.select();
      navigator.clipboard.writeText(input.value);
      showToast("OPDS catalog URL copied!");
    }

    async function submitSendKindle() {
      if (!activeSendBookId) return;
      const email = document.getElementById("sendKindleEmailInput").value.trim();
      const statusMsg = document.getElementById("sendKindleStatusMsg");
      const btn = document.getElementById("sendKindleBtn");

      if (!email) {
        alert("Please enter your @kindle.com email address.");
        return;
      }

      btn.disabled = true;
      btn.textContent = "Sending to Kindle...";
      statusMsg.style.display = "block";
      statusMsg.style.color = "var(--text-muted)";
      statusMsg.textContent = "Connecting to mail server & transmitting book file...";

      try {
        const res = await fetch(`/books/${activeSendBookId}/send-kindle`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ kindle_email: email })
        });
        const data = await res.json();
        if (!res.ok) {
          statusMsg.style.color = "#fca5a5";
          statusMsg.textContent = "❌ " + (data.detail || "Failed to send.");
        } else {
          statusMsg.style.color = "#6ee7b7";
          statusMsg.textContent = "✅ " + data.message;
          showToast("Sent to your Kindle!");
        }
      } catch (err) {
        statusMsg.style.color = "#fca5a5";
        statusMsg.textContent = "❌ Network error: " + err.message;
      } finally {
        btn.disabled = false;
        btn.textContent = "🚀 Send to Kindle Now";
      }
    }

    // --- SETTINGS MODAL ---
    async function openSettingsModal() {
      const modal = document.getElementById("settingsModal");
      const info = await fetchDeviceInfo();
      const s = info?.settings || {};

      document.getElementById("settingKindleEmail").value = s.kindle_email || "";
      document.getElementById("settingFromEmail").value = s.from_email || s.smtp_user || "";
      document.getElementById("settingSmtpHost").value = s.smtp_host || "";
      document.getElementById("settingSmtpPort").value = s.smtp_port || "587";
      document.getElementById("settingSmtpUser").value = s.smtp_user || "";
      document.getElementById("settingSmtpPassword").value = s.smtp_password_set ? "••••••••" : "";

      modal.classList.add("open");
    }

    function closeSettingsModal() {
      document.getElementById("settingsModal").classList.remove("open");
    }

    function applySmtpPreset(provider) {
      const hostInput = document.getElementById("settingSmtpHost");
      const portInput = document.getElementById("settingSmtpPort");
      if (provider === "gmail") {
        hostInput.value = "smtp.gmail.com";
        portInput.value = "587";
      } else if (provider === "outlook") {
        hostInput.value = "smtp.office365.com";
        portInput.value = "587";
      } else if (provider === "icloud") {
        hostInput.value = "smtp.mail.me.com";
        portInput.value = "587";
      } else if (provider === "yahoo") {
        hostInput.value = "smtp.mail.yahoo.com";
        portInput.value = "465";
      }
      showToast(`Applied ${provider} SMTP preset`);
    }

    async function submitSettings(e) {
      e.preventDefault();
      const payload = {
        kindle_email: document.getElementById("settingKindleEmail").value,
        from_email: document.getElementById("settingFromEmail").value,
        smtp_host: document.getElementById("settingSmtpHost").value,
        smtp_port: document.getElementById("settingSmtpPort").value,
        smtp_user: document.getElementById("settingSmtpUser").value,
        smtp_password: document.getElementById("settingSmtpPassword").value,
      };

      const res = await fetch("/system/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        showToast("Settings saved successfully!");
        closeSettingsModal();
      } else {
        alert("Failed to save settings");
      }
    }

    // --- REVIEW SYSTEM LOGIC ---
    function openReviewModal(bookId) {
      const book = allBooks.find(b => b.id === bookId);
      if (!book) return;

      document.getElementById("reviewBookId").value = book.id;
      document.getElementById("reviewModalTitle").textContent = `✍️ Review: "${book.title}"`;

      const coverImg = document.getElementById("reviewBannerCover");
      if (book.cover_url) {
        coverImg.src = book.cover_url;
        coverImg.style.display = "block";
      } else {
        coverImg.style.display = "none";
      }

      document.getElementById("reviewBannerTitle").textContent = book.title;
      document.getElementById("reviewBannerAuthor").textContent = `by ${book.author}`;
      const formatStr = book.media_type === "audiobook" ? "🎧 Audiobook" : "📚 Ebook";
      const seriesStr = book.series_name ? ` • 📖 ${book.series_name}${book.series_number ? ' #' + book.series_number : ''}` : "";
      document.getElementById("reviewBannerMeta").textContent = `${formatStr}${seriesStr}`;

      document.getElementById("reviewRatingSelect").value = String(book.rating || 0);
      document.getElementById("reviewSpiceSelect").value = String(book.spice_rating || 0);
      document.getElementById("reviewPaceSelect").value = book.pace || "";
      document.getElementById("reviewHeadlineInput").value = book.review_headline || "";
      document.getElementById("reviewTextInput").value = book.review || "";
      document.getElementById("reviewQuotesInput").value = book.favorite_quotes || "";
      document.getElementById("reviewCharactersInput").value = book.favorite_characters || "";
      document.getElementById("reviewTropesInput").value = book.tropes || "";
      document.getElementById("reviewMarkAsReadCheck").checked = Boolean(book.is_read || book.rating);

      document.getElementById("reviewModal").classList.add("open");
    }

    function closeReviewModal() {
      document.getElementById("reviewModal").classList.remove("open");
    }

    async function submitReviewForm(e) {
      e.preventDefault();
      const bookId = document.getElementById("reviewBookId").value;
      if (!bookId) return;

      const btn = document.getElementById("saveReviewBtn");
      btn.disabled = true;
      btn.textContent = "Saving...";

      const payload = {
        rating: parseInt(document.getElementById("reviewRatingSelect").value || "0", 10),
        spice_rating: parseInt(document.getElementById("reviewSpiceSelect").value || "0", 10),
        pace: document.getElementById("reviewPaceSelect").value,
        review_headline: document.getElementById("reviewHeadlineInput").value.trim(),
        review: document.getElementById("reviewTextInput").value.trim(),
        favorite_quotes: document.getElementById("reviewQuotesInput").value.trim(),
        favorite_characters: document.getElementById("reviewCharactersInput").value.trim(),
        tropes: document.getElementById("reviewTropesInput").value.trim(),
        mark_as_read: document.getElementById("reviewMarkAsReadCheck").checked
      };

      try {
        const res = await fetch(`/books/${bookId}/review`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        if (res.ok) {
          closeReviewModal();
          showToast("Saved review & thoughts!");
          await loadBooks(document.getElementById("searchInput").value);
        } else {
          alert("Failed to save review");
        }
      } catch (err) {
        alert("Error saving review: " + err.message);
      } finally {
        btn.disabled = false;
        btn.textContent = "💾 Save Review";
      }
    }

    async function clearReview(bookId, title) {
      if (!confirm(`Are you sure you want to clear your review and rating for "${title}"?`)) return;
      try {
        const res = await fetch(`/books/${bookId}/review/clear`, { method: "POST" });
        if (res.ok) {
          showToast("Review cleared");
          await loadBooks(document.getElementById("searchInput").value);
        }
      } catch (err) {
        alert("Error clearing review");
      }
    }

    // Live search inside the Reviews view
    function handleReviewBookSearch(val) {
      const dropdown = document.getElementById("reviewSearchResults");
      if (!dropdown) return;

      const q = (val || "").trim().toLowerCase();
      if (!q) {
        dropdown.style.display = "none";
        return;
      }

      const matches = allBooks.filter(b =>
        (b.title && b.title.toLowerCase().includes(q)) ||
        (b.author && b.author.toLowerCase().includes(q)) ||
        (b.series_name && b.series_name.toLowerCase().includes(q))
      ).slice(0, 8);

      if (!matches.length) {
        dropdown.innerHTML = `<div style="padding:0.75rem 1rem; font-size:0.83rem; color:var(--text-muted);">No books found matching "${escapeHtml(val)}"</div>`;
        dropdown.style.display = "block";
        return;
      }

      dropdown.innerHTML = matches.map(b => {
        const hasRev = (b.rating > 0) || (b.review && b.review.trim()) || (b.favorite_quotes && b.favorite_quotes.trim());
        const badge = hasRev ? `⭐ ${b.rating}/5` : `<span style="color:#6ee7b7;">＋ Review</span>`;
        const formatIcon = b.media_type === "audiobook" ? "🎧" : "📚";
        return `
          <div class="review-search-item" onclick="selectReviewSearchBook(${b.id})">
            ${b.cover_url
              ? `<img src="${escapeHtml(b.cover_url)}" alt="" onerror="this.style.display='none'" />`
              : `<div style="width:32px; height:48px; border-radius:4px; background:#312e81; display:flex; align-items:center; justify-content:center; font-size:0.75rem;">${formatIcon}</div>`
            }
            <div style="flex:1; min-width:0;">
              <div style="font-weight:600; font-size:0.88rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${escapeHtml(b.title)}</div>
              <div style="font-size:0.75rem; color:var(--text-muted);">${escapeHtml(b.author)} • ${formatIcon} ${b.media_type}</div>
            </div>
            <div style="font-size:0.78rem; font-weight:700;">${badge}</div>
          </div>
        `;
      }).join("");

      dropdown.style.display = "block";
    }

    function selectReviewSearchBook(bookId) {
      const dropdown = document.getElementById("reviewSearchResults");
      if (dropdown) dropdown.style.display = "none";
      const input = document.getElementById("reviewSearchInput");
      if (input) input.value = "";
      openReviewModal(bookId);
    }

    // Close review search dropdown when clicking outside
    document.addEventListener("click", (e) => {
      const dropdown = document.getElementById("reviewSearchResults");
      const searchBox = document.querySelector(".review-search-box");
      if (dropdown && searchBox && !searchBox.contains(e.target)) {
        dropdown.style.display = "none";
      }
    });

    // Book Picker Modal
    function openReviewPickerModal() {
      const modal = document.getElementById("reviewPickerModal");
      const filterInput = document.getElementById("reviewPickerFilter");
      if (filterInput) filterInput.value = "";
      filterReviewPickerList("");
      modal.classList.add("open");
    }

    function closeReviewPickerModal() {
      document.getElementById("reviewPickerModal").classList.remove("open");
    }

    function filterReviewPickerList(q) {
      const container = document.getElementById("reviewPickerList");
      if (!container) return;

      const query = (q || "").trim().toLowerCase();
      const list = allBooks.filter(b =>
        !query ||
        (b.title && b.title.toLowerCase().includes(query)) ||
        (b.author && b.author.toLowerCase().includes(query)) ||
        (b.series_name && b.series_name.toLowerCase().includes(query))
      );

      if (!list.length) {
        container.innerHTML = `<div style="padding:1.5rem; text-align:center; color:var(--text-muted); font-size:0.88rem;">No books match "${escapeHtml(q)}"</div>`;
        return;
      }

      container.innerHTML = list.map(b => {
        const hasRev = (b.rating > 0) || (b.review && b.review.trim()) || (b.favorite_quotes && b.favorite_quotes.trim());
        const formatIcon = b.media_type === "audiobook" ? "🎧" : "📚";
        return `
          <div style="display:flex; align-items:center; gap:0.85rem; padding:0.65rem 0.85rem; background:rgba(255,255,255,0.02); border:1px solid var(--border); border-radius:8px; cursor:pointer;" onclick="closeReviewPickerModal(); openReviewModal(${b.id});" onmouseover="this.style.background='rgba(99,102,241,0.12)'" onmouseout="this.style.background='rgba(255,255,255,0.02)'">
            ${b.cover_url
              ? `<img src="${escapeHtml(b.cover_url)}" style="width:36px; height:52px; object-fit:cover; border-radius:4px; flex-shrink:0;" alt="" onerror="this.style.display='none'" />`
              : `<div style="width:36px; height:52px; border-radius:4px; background:#312e81; display:flex; align-items:center; justify-content:center; flex-shrink:0;">${formatIcon}</div>`
            }
            <div style="flex:1; min-width:0;">
              <div style="font-weight:600; font-size:0.92rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${escapeHtml(b.title)}</div>
              <div style="font-size:0.78rem; color:var(--text-muted);">${escapeHtml(b.author)} • ${formatIcon} ${b.media_type}${b.series_name ? ` • 📖 ${escapeHtml(b.series_name)}` : ''}</div>
            </div>
            <div>
              ${hasRev
                ? `<span class="badge" style="background:rgba(245,158,11,0.18); color:#fcd34d;">★ ${b.rating}/5</span>`
                : `<button class="btn btn-primary btn-sm" style="pointer-events:none;">✍️ Review</button>`
              }
            </div>
          </div>
        `;
      }).join("");
    }

    loadBooks();
  