import { BrowserRouter, Routes, Route, Link } from 'react-router-dom';
import DisputeFormPage from './pages/DisputeFormPage';
import DisputeListPage from './pages/DisputeListPage';
import DisputeDetailPage from './pages/DisputeDetailPage';

function App() {
  return (
    <BrowserRouter>
      <nav style={{ backgroundColor: '#1a1f71', padding: '16px 24px', display: 'flex', alignItems: 'center', gap: '24px' }}>
        <span style={{ color: 'white', fontWeight: 'bold', fontSize: '18px' }}>Visa Disputes</span>
        <Link to="/" style={{ color: 'white', textDecoration: 'none' }}>New Dispute</Link>
        <Link to="/disputes" style={{ color: 'white', textDecoration: 'none' }}>All Disputes</Link>
      </nav>
      <main style={{ padding: '24px' }}>
        <Routes>
          <Route path="/" element={<DisputeFormPage />} />
          <Route path="/disputes" element={<DisputeListPage />} />
          <Route path="/disputes/:caseId" element={<DisputeDetailPage />} />
        </Routes>
      </main>
    </BrowserRouter>
  );
}

export default App;
