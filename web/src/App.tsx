import { BrowserRouter, Route, Routes } from 'react-router-dom'
import Layout from './Layout'
import StartPage from './pages/StartPage'
import ScanPage from './pages/ScanPage'
import ScansPage from './pages/ScansPage'
import BrandsPage from './pages/BrandsPage'
import BrandPage from './pages/BrandPage'
import BatchPage from './pages/BatchPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<StartPage />} />
          <Route path="scans" element={<ScansPage />} />
          <Route path="scans/:id" element={<ScanPage />} />
          <Route path="batches/:id" element={<BatchPage />} />
          <Route path="brands" element={<BrandsPage />} />
          <Route path="brands/:id" element={<BrandPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
