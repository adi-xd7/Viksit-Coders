import React from 'react';

export interface BadgeProps {
  variant?: 'verified' | 'established' | 'contested' | 'conceded' | 'danger' | 'warning' | 'healthy' | 'neutral';
  children: React.ReactNode;
  className?: string;
}

export const Badge: React.FC<BadgeProps> = ({ variant = 'neutral', children, className = '' }) => {
  return <span className={`badge badge-${variant} ${className}`}>{children}</span>;
};
