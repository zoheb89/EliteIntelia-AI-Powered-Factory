import {FactoryProvider} from '../../lib/factory-context';

export default function FactoryLayout({children}: {children: React.ReactNode}) {
  return <FactoryProvider>{children}</FactoryProvider>;
}
