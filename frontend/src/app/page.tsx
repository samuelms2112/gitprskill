import { redirect } from 'next/navigation';

/** Raiz: o layout protegido decide entre o painel e o login. */
export default function HomePage() {
  redirect('/dashboard');
}
