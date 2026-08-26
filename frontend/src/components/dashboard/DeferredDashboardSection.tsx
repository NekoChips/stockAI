import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Skeleton, Typography } from 'antd';

interface DeferredDashboardSectionProps {
  title: string;
  minHeight: number;
  rootMargin?: string;
  children: ReactNode;
}

function SectionPlaceholder({ title, minHeight }: Pick<DeferredDashboardSectionProps, 'title' | 'minHeight'>) {
  return (
    <div
      className="dashboard-deferred-placeholder"
      style={{ minHeight }}
      role="status"
      aria-label={`${title}加载中`}
    >
      <div className="dashboard-deferred-placeholder-heading">
        <Typography.Text strong>{title}</Typography.Text>
        <Typography.Text type="secondary">即将加载</Typography.Text>
      </div>
      <Skeleton active title={{ width: '34%' }} paragraph={{ rows: 3, width: ['100%', '88%', '64%'] }} />
    </div>
  );
}

export function DeferredDashboardSection({
  title,
  minHeight,
  rootMargin = '320px 0px',
  children,
}: DeferredDashboardSectionProps) {
  const sectionRef = useRef<HTMLElement>(null);
  const [shouldLoad, setShouldLoad] = useState(false);

  useEffect(() => {
    const section = sectionRef.current;
    if (!section) return;

    if (!('IntersectionObserver' in window)) {
      setShouldLoad(true);
      return;
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setShouldLoad(true);
          observer.disconnect();
        }
      },
      { rootMargin },
    );
    observer.observe(section);
    return () => observer.disconnect();
  }, [rootMargin]);

  return (
    <section
      ref={sectionRef}
      className="dashboard-deferred-section"
      style={{ minHeight }}
      aria-busy={!shouldLoad}
    >
      {shouldLoad ? (
        <>{children}</>
      ) : (
        <SectionPlaceholder title={title} minHeight={minHeight} />
      )}
    </section>
  );
}

export function DeferredSectionFallback({ title, minHeight }: { title: string; minHeight: number }) {
  return <SectionPlaceholder title={title} minHeight={minHeight} />;
}
